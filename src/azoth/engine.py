"""Finds a conversion route and runs it safely.

A route can have several steps, e.g. PowerPoint → PDF → PNG. Intermediate
files live in a private temporary folder that is always deleted afterwards,
also when the conversion fails or is cancelled. Results are written under a
new name if the target already exists, so nothing is ever silently
overwritten, and the original is never touched.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import formats, quality, ranking
from .converters import (
    ConversionContext,
    ConversionError,
    Converter,
    all_converters,
)

MAX_STEPS = 3


@dataclass(frozen=True)
class Step:
    src: str
    dst: str
    converter: Converter


@dataclass
class ConversionResult:
    source: Path
    outputs: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Engine:
    def __init__(
        self,
        converters: Iterable[Converter] | None = None,
        *,
        assume_available: bool = False,
    ) -> None:
        """``assume_available=True`` plans routes as if every engine (e.g. LibreOffice)
        were installed. Used to list what's possible, never to run conversions."""
        self.converters = list(converters) if converters is not None else all_converters()
        self._edges: dict[str, dict[str, Converter]] = {}
        for conv in sorted(self.converters, key=lambda c: c.priority):
            if not assume_available and not conv.is_available():
                continue
            for src, dst in conv.capabilities():
                self._edges.setdefault(src, {})[dst] = conv  # higher priority overwrites

    def unavailable(self) -> list[Converter]:
        """Required converters whose engine is missing (optional ones like Word are left out)."""
        return [c for c in self.converters if not c.optional and not c.is_available()]

    def uses_word(self) -> bool:
        return any(c.id == "msword" and c.is_available() for c in self.converters)

    # --- route finding ------------------------------------------------------

    def find_route(self, src: str, dst: str) -> list[Step] | None:
        """Shortest chain of converters from ``src`` to ``dst`` (breadth-first search)."""
        if src == dst:
            return None
        queue: deque[tuple[str, list[Step]]] = deque([(src, [])])
        seen = {src}
        while queue:
            current, path = queue.popleft()
            if len(path) >= MAX_STEPS:
                continue
            for nxt, conv in self._edges.get(current, {}).items():
                if path and conv.first_only(current, nxt):
                    continue  # only allowed on the original file
                step = Step(current, nxt, conv)
                if nxt == dst:
                    return [*path, step]
                if nxt in seen or conv.final_only(current, nxt):
                    continue  # e.g. multi-file results can only be the final step
                seen.add(nxt)
                queue.append((nxt, [*path, step]))
        return None

    def targets_for(self, src: str) -> list[formats.Format]:
        """All formats ``src`` can be converted to, most useful first (see ranking.py)."""
        result = []
        for fmt in formats.FORMATS.values():
            if fmt.id != src and self.find_route(src, fmt.id) is not None:
                result.append(fmt)
        source = formats.FORMATS.get(src)
        return ranking.rank(result, [source.category] if source else [])

    def quality_notes(self, route: list[Step]) -> list[str]:
        notes = []
        for step in route:
            note = step.converter.quality_note(step.src, step.dst)
            if note and note not in notes:
                notes.append(note)
        return notes

    # --- running ------------------------------------------------------------

    def convert(
        self,
        source: Path | str,
        target: str,
        output_dir: Path | str | None = None,
        *,
        options: dict[str, Any] | None = None,
        overwrite: bool = False,
        progress: Callable[[float, str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ConversionResult:
        source = Path(source)
        if not source.is_file():
            raise ConversionError(f"File not found: {source}")
        src_fmt = formats.detect(source)
        if src_fmt is None:
            raise ConversionError(f"Unknown file type: {source.name}")
        try:
            dst_fmt = formats.get(target)
        except KeyError as exc:
            raise ConversionError(str(exc)) from exc
        if src_fmt.id == dst_fmt.id:
            raise ConversionError(f"{source.name} is already {dst_fmt.name}")

        route = self.find_route(src_fmt.id, dst_fmt.id)
        if route is None:
            hint = ""
            for conv in self.unavailable():
                if any(src_fmt.id in pair or dst_fmt.id in pair for pair in conv.capabilities()):
                    hint = " " + conv.unavailable_reason()
                    break
            raise ConversionError(f"Cannot convert {src_fmt.name} to {dst_fmt.name}.{hint}")

        out_dir = Path(output_dir) if output_dir is not None else source.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        report = progress or (lambda f, m: None)
        cancel = cancel_event or threading.Event()
        result = ConversionResult(source=source, notes=self.quality_notes(route))
        resolved_options = quality.resolve_options(options)  # level → values, enforce limits

        with tempfile.TemporaryDirectory(prefix="azoth-") as tmp:
            tmp_path = Path(tmp)
            current = source
            if source.suffix.lower().lstrip(".") not in src_fmt.extensions:
                # Wrong or missing extension: give converters a correctly named copy.
                current = tmp_path / f"source.{src_fmt.extension}"
                shutil.copyfile(source, current)
            for i, step in enumerate(route):
                last = i == len(route) - 1
                step_dir = tmp_path / f"step{i}"
                step_dir.mkdir()
                ext = formats.FORMATS[step.dst].extension
                step_dst = (step_dir / "out" if last else step_dir) / f"{source.stem}.{ext}"
                step_dst.parent.mkdir(exist_ok=True)

                def step_progress(fraction: float, message: str, _i: int = i) -> None:
                    overall = (_i + max(0.0, min(1.0, fraction))) / len(route)
                    report(overall, message)

                ctx = ConversionContext(
                    work_dir=step_dir,
                    options=resolved_options,
                    progress=step_progress,
                    cancel_event=cancel,
                )
                ctx.check_cancelled()
                produced = step.converter.convert(current, step_dst, ctx)
                if not produced or not all(p.exists() for p in produced):
                    raise ConversionError("The converter did not produce any output")
                if not last:
                    current = produced[0]
                else:
                    for p in produced:
                        final = out_dir / p.name
                        if not overwrite or final.resolve() == source.resolve():
                            final = unique_path(final)
                        shutil.move(str(p), final)
                        result.outputs.append(final)
        report(1.0, "Done")
        return result


def unique_path(path: Path) -> Path:
    """``report.pdf`` → ``report (1).pdf`` if the name is already taken."""
    if not path.exists():
        return path
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1
