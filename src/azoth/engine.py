"""Finds a conversion route and runs it safely.

A route can have several steps, e.g. PowerPoint → PDF → PNG. Intermediate
files live in a private temporary folder that is always deleted afterwards,
also when the conversion fails or is cancelled. Results are written under a
new name if the target already exists, so nothing is ever silently
overwritten, and the original is never touched.
"""

from __future__ import annotations

import os
import queue
import shutil
import tempfile
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import formats, quality, ranking
from .converters import (
    ConversionCancelled,
    ConversionContext,
    ConversionError,
    Converter,
    RetryAlone,
    all_converters,
)

MAX_STEPS = 3
BATCH_SIZE = 10  # files per engine start in convert_many (LibreOffice)
# Photos converted at the same time in convert_many: one CPU core stays free for the window.
PARALLEL_FILES = max(1, min(4, (os.cpu_count() or 1) - 1))
_OUTPUT_LOCK = threading.Lock()  # choosing a free name and moving the result in place
TEMP_PREFIX = "azoth-"  # every job's private temp folder starts with this


def cleanup_stale_temp_folders(max_age_hours: float = 6.0) -> int:
    """Delete job folders left behind by a crash or a forced shutdown.

    Normally each job removes its own folder. Only folders older than
    ``max_age_hours`` are removed, so a conversion running in another window is
    never disturbed. Returns the number of folders removed.
    """
    import time

    root = Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for folder in root.glob(f"{TEMP_PREFIX}*"):
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
                removed += not folder.exists()
        except OSError:
            continue
    return removed


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
    warnings: list[str] = field(default_factory=list)  # see ConversionContext.warnings


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
        # Routes and target lists never change for an engine (which converters are
        # available is decided here), so they are worked out once and remembered.
        self._routes: dict[tuple[str, str], list[Step] | None] = {}
        self._targets: dict[str, list[formats.Format]] = {}
        for conv in sorted(self.converters, key=lambda c: c.priority):
            if not assume_available and not conv.is_available():
                continue
            for src, dst in conv.capabilities():
                self._edges.setdefault(src, {})[dst] = conv  # higher priority overwrites

    def unavailable(self) -> list[Converter]:
        """Required converters whose engine is missing (optional ones like Word are left out)."""
        return [c for c in self.converters if not c.optional and not c.is_available()]

    def missing(self, converter: Converter) -> list[tuple[str, str]]:
        """Conversions of ``converter`` that no available engine can do (e.g. without
        LibreOffice, Excel files when Microsoft Excel isn't installed either)."""
        available = [c for c in self.converters if c.is_available()]
        return [
            pair
            for pair in converter.capabilities()
            if not any(pair in set(c.capabilities()) for c in available)
        ]

    def needed_engines(self) -> list[tuple[Converter, list[tuple[str, str]]]]:
        """Missing engines that would add conversions, with those conversions."""
        result = []
        for conv in self.unavailable():
            missing = self.missing(conv)
            if missing:
                result.append((conv, missing))
        return result

    def uses_word(self) -> bool:
        return any(c.id == "msword" and c.is_available() for c in self.converters)

    # --- route finding ------------------------------------------------------

    def find_route(self, src: str, dst: str) -> list[Step] | None:
        """Shortest chain of converters from ``src`` to ``dst`` (breadth-first search)."""
        key = (src, dst)
        if key not in self._routes:
            self._routes[key] = self._search_route(src, dst)
        route = self._routes[key]
        return None if route is None else list(route)

    def _search_route(self, src: str, dst: str) -> list[Step] | None:
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

    def resize_route(self, fmt: str) -> list[Step] | None:
        """Saving a ``fmt`` file again in the same format, in a new size (option ``resize``)."""
        for conv in sorted(self.converters, key=lambda c: -c.priority):
            if conv.is_available() and conv.supports_resize(fmt, fmt):
                return [Step(fmt, fmt, conv)]
        return None

    def shrink_route(self, fmt: str) -> list[Step] | None:
        """Saving a ``fmt`` video as a smaller MP4 (option ``shrink``), in one step."""
        for conv in sorted(self.converters, key=lambda c: -c.priority):
            if conv.is_available() and conv.supports_shrink(fmt):
                return [Step(fmt, "mp4", conv)]
        return None

    def can_shrink(self, fmt: str) -> bool:
        return self.shrink_route(fmt) is not None

    def can_resize(self, src: str, dst: str) -> bool:
        """True if ``src`` files can get a new picture size when converted to ``dst``
        (or saved again in a new size, when ``src == dst``)."""
        route = self.resize_route(src) if src == dst else self.find_route(src, dst)
        return route is not None and route[-1].converter.supports_resize(
            route[-1].src, route[-1].dst
        )

    def targets_for(self, src: str) -> list[formats.Format]:
        """All formats ``src`` can be converted to, most useful first (see ranking.py)."""
        if src not in self._targets:
            self._targets[src] = self._search_targets(src)
        return list(self._targets[src])

    def _search_targets(self, src: str) -> list[formats.Format]:
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
        name: str | None = None,
    ) -> ConversionResult:
        """``name``: the result's file name without extension (default: the original's)."""
        resolved = quality.resolve_options(options)  # level → values, enforce limits
        job = self._plan(Path(source), target, output_dir, name, resolved)
        return self._run(
            job,
            resolved,
            overwrite=overwrite,
            report=progress or (lambda f, m: None),
            cancel=cancel_event or threading.Event(),
        )

    def convert_many(
        self,
        sources: Iterable[Path | str],
        target: str,
        output_dir: Path | str | None = None,
        *,
        options: dict[str, Any] | None = None,
        overwrite: bool = False,
        started: Callable[[int], None] | None = None,
        progress: Callable[[int, float, str], None] | None = None,
        cancel_event: threading.Event | None = None,
        batch_size: int = BATCH_SIZE,
        parallel: int = PARALLEL_FILES,
    ) -> Iterator[tuple[int, ConversionResult | Exception]]:
        """Convert several files, in order. Yields (index, result or the error) per file.

        Same results as calling :meth:`convert` for each file, only faster: where an engine
        can do several files at once (LibreOffice), the first step is done for up to
        ``batch_size`` files in one go. A file that fails in such a batch is simply tried
        again on its own, so its error message is the same as with :meth:`convert`.
        Files whose engines allow it (photos, see ``Converter.parallel_safe``) are
        converted ``parallel`` at a time. ``started`` and ``progress`` are always called
        from the thread that iterates, and a file's calls always come before its result.
        Stops after a cancelled file. ``started(index)`` is called before each file.
        """
        sources = [Path(s) for s in sources]
        resolved = quality.resolve_options(options)
        cancel = cancel_event or threading.Event()
        jobs: list[_Job | ConversionError] = []
        for source in sources:
            try:
                jobs.append(self._plan(source, target, output_dir, None, resolved))
            except ConversionError as exc:
                jobs.append(exc)

        # Parallel threads only queue their messages; pump() passes them on from here.
        messages: queue.SimpleQueue = queue.SimpleQueue()

        def pump() -> None:
            while True:
                try:
                    i, args = messages.get_nowait()
                except queue.Empty:
                    return
                if args is None:
                    if started:
                        started(i)
                elif progress:
                    progress(i, *args)

        def reporter(i: int) -> Callable[[float, str], None]:
            def report(fraction: float, message: str) -> None:
                pump()
                if progress:
                    progress(i, fraction, message)

            return report

        def run_alone(i: int, job: _Job) -> ConversionResult:
            if cancel.is_set():
                raise ConversionCancelled()
            messages.put((i, None))
            return self._run(
                job, resolved, overwrite=overwrite, cancel=cancel,
                report=lambda f, m: messages.put((i, (f, m))),
            )  # fmt: skip

        futures: dict[int, Future] = {}
        with (
            tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as tmp,
            ThreadPoolExecutor(max_workers=max(1, parallel)) as pool,
        ):
            try:
                if parallel > 1:
                    for i, job in enumerate(jobs):
                        if isinstance(job, _Job) and all(
                            s.converter.parallel_safe for s in job.route
                        ):
                            futures[i] = pool.submit(run_alone, i, job)
                yield from self._many(
                    jobs, futures, Path(tmp), resolved, overwrite, started, reporter, pump,
                    cancel, batch_size,
                )  # fmt: skip
            finally:
                for future in futures.values():
                    future.cancel()  # those not started yet; running ones end by themselves

    def _many(
        self,
        jobs: list[_Job | ConversionError],
        futures: dict[int, Future],
        tmp: Path,
        options: dict[str, Any],
        overwrite: bool,
        started: Callable[[int], None] | None,
        reporter: Callable[[int], Callable[[float, str], None]],
        pump: Callable[[], None],
        cancel: threading.Event,
        batch_size: int,
    ) -> Iterator[tuple[int, ConversionResult | Exception]]:
        done_first: dict[int, list[Path] | ConversionError] = {}
        for i, job in enumerate(jobs):
            if cancel.is_set():
                return
            pump()
            if i in futures:  # running in a parallel thread
                while not wait([futures[i]], timeout=0.05, return_when=FIRST_COMPLETED).done:
                    pump()
                pump()  # its last messages before its result
                try:
                    yield i, futures[i].result()
                except Exception as exc:  # noqa: BLE001 - handed to the caller
                    yield i, exc
                    if isinstance(exc, ConversionCancelled):
                        return
                continue
            if started:
                started(i)
            report = reporter(i)
            if isinstance(job, ConversionError):
                yield i, job
                continue
            if i not in done_first:
                try:
                    self._batch_first_steps(
                        jobs, i, batch_size, tmp / f"batch{i}", options, report, cancel,
                        done_first,
                    )  # fmt: skip
                except ConversionCancelled as exc:
                    yield i, exc
                    return
                except Exception:  # noqa: BLE001 - the files are then done one by one
                    pass
            first = done_first.pop(i, None)
            try:
                if isinstance(first, ConversionError):
                    raise first
                result = self._run(
                    job, options, overwrite=overwrite, report=report, cancel=cancel, first=first
                )
            except Exception as exc:  # noqa: BLE001 - handed to the caller
                yield i, exc
                if isinstance(exc, ConversionCancelled):
                    return
            else:
                yield i, result

    # --- internals ----------------------------------------------------------

    def _plan(
        self,
        source: Path,
        target: str,
        output_dir: Path | str | None,
        name: str | None,
        options: dict[str, Any],
    ) -> _Job:
        if not source.is_file():
            raise ConversionError(f"File not found: {source}")
        src_fmt = formats.detect(source)
        if src_fmt is None:
            raise ConversionError(f"Unknown file type: {source.name}")
        try:
            dst_fmt = formats.get(target)
        except KeyError as exc:
            raise ConversionError(str(exc)) from exc
        resizing = options.get("resize") is not None
        shrinking = bool(options.get("shrink"))
        if shrinking:
            route = self.shrink_route(src_fmt.id) if dst_fmt.id == "mp4" else None
            if route is None and (src_fmt.category != formats.VIDEO or dst_fmt.id != "mp4"):
                raise ConversionError(
                    f"{source.name} can't be made smaller: only videos can, as MP4."
                )
        elif src_fmt.id == dst_fmt.id:
            route = self.resize_route(src_fmt.id) if resizing else None
            if route is None:
                raise ConversionError(f"{source.name} is already {dst_fmt.name}")
        else:
            route = self.find_route(src_fmt.id, dst_fmt.id)
        if route is None:
            hint = ""
            for conv in self.unavailable():
                if any(src_fmt.id in pair or dst_fmt.id in pair for pair in conv.capabilities()):
                    hint = " " + conv.unavailable_reason()
                    break
            raise ConversionError(f"Cannot convert {src_fmt.name} to {dst_fmt.name}.{hint}")
        last = route[-1]
        if resizing and not last.converter.supports_resize(last.src, last.dst):
            raise ConversionError(
                f"The picture size can't be changed when converting {src_fmt.name} to "
                f"{dst_fmt.name}. Only pictures saved as pictures can get a new size."
            )
        if name is not None:
            stem = check_file_name(name, dst_fmt.extension)
        elif shrinking:
            stem = f"{source.stem} (smaller)"  # never the original's name
        elif src_fmt.id == dst_fmt.id:
            ai = getattr(options.get("resize"), "ai", False)
            stem = f"{source.stem} ({'enhanced' if ai else 'resized'})"  # never the original's name
        else:
            stem = source.stem
        out_dir = Path(output_dir) if output_dir is not None else source.parent
        return _Job(source, src_fmt, route, stem, out_dir)

    def _batch_first_steps(
        self,
        jobs: list[_Job | ConversionError],
        index: int,
        batch_size: int,
        work_dir: Path,
        options: dict[str, Any],
        report: Callable[[float, str], None],
        cancel: threading.Event,
        done_first: dict[int, list[Path] | ConversionError],
    ) -> None:
        """Do the first step of ``jobs[index]`` together with the next files that can join
        it (same engine and :meth:`Converter.batch_key`). Results go into ``done_first``."""
        job = jobs[index]
        assert isinstance(job, _Job)
        step = job.route[0]
        key = step.converter.batch_key(step.src, step.dst)
        if key is None:
            return
        group = [index]
        for j in range(index + 1, len(jobs)):
            if len(group) >= batch_size:
                break
            other = jobs[j]
            if (
                isinstance(other, _Job)
                and j not in done_first
                and other.route[0].converter is step.converter
                and other.route[0].converter.batch_key(other.route[0].src, other.route[0].dst)
                == key
            ):
                group.append(j)
        if len(group) < 2:
            return
        pairs = []
        for n, j in enumerate(group):
            other = jobs[j]
            assert isinstance(other, _Job)
            folder = work_dir / f"file{n}"
            folder.mkdir(parents=True)
            pairs.append((other.readable_source(folder, options), other.step_target(0, folder)))
        report(0.0, f"Converting {len(group)} files at once with {step.converter.label}")
        ctx = ConversionContext(
            work_dir=work_dir,
            options=options if len(job.route) == 1 else _without_resize(options),
            progress=lambda f, m: report(max(0.0, min(1.0, f)) / len(job.route), m),
            cancel_event=cancel,
        )
        results = step.converter.convert_batch(pairs, ctx)
        for j, (_, dst), error in zip(group, pairs, results, strict=True):
            if error is None and dst.exists():
                done_first[j] = [dst]
            elif error is not None and not isinstance(error, RetryAlone):
                done_first[j] = error

    def _run(
        self,
        job: _Job,
        options: dict[str, Any],
        *,
        overwrite: bool,
        report: Callable[[float, str], None],
        cancel: threading.Event,
        first: list[Path] | None = None,
    ) -> ConversionResult:
        """Run the route of ``job``. ``first``: the files step 1 already produced (batch)."""
        source, route = job.source, job.route
        job.out_dir.mkdir(parents=True, exist_ok=True)
        result = ConversionResult(source=source, notes=self.quality_notes(route))
        with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as tmp:
            tmp_path = Path(tmp)
            current = job.readable_source(tmp_path, options)
            produced: list[Path] = []
            for i, step in enumerate(route):
                if i == 0 and first is not None:
                    produced = first
                else:
                    step_dir = tmp_path / f"step{i}"
                    step_dir.mkdir()
                    step_dst = job.step_target(i, step_dir)

                    def step_progress(fraction: float, message: str, _i: int = i) -> None:
                        overall = (_i + max(0.0, min(1.0, fraction))) / len(route)
                        report(overall, message)

                    ctx = ConversionContext(
                        work_dir=step_dir,
                        options=options if i == len(route) - 1 else _without_resize(options),
                        progress=step_progress,
                        cancel_event=cancel,
                    )
                    ctx.check_cancelled()
                    produced = step.converter.convert(current, step_dst, ctx)
                    result.warnings.extend(ctx.warnings)
                    result.notes.extend(ctx.notes)
                if not produced or not all(p.exists() for p in produced):
                    raise ConversionError("The converter did not produce any output")
                current = produced[0]
            with _OUTPUT_LOCK:  # two files converted at once may want the same name
                for p in produced:
                    final = job.out_dir / p.name
                    if not overwrite or final.resolve() == source.resolve():
                        final = unique_path(final)
                    shutil.move(str(p), final)
                    result.outputs.append(final)
        report(1.0, "Done")
        return result


def _without_resize(options: dict[str, Any]) -> dict[str, Any]:
    """Options for steps before the last: the size is changed once, at the end."""
    return {k: v for k, v in options.items() if k != "resize"}


def _no_progress(fraction: float, message: str) -> None:
    pass


@dataclass
class _Job:
    """One file with its planned route."""

    source: Path
    src_fmt: formats.Format
    route: list[Step]
    stem: str
    out_dir: Path

    def readable_source(self, folder: Path, options: dict[str, Any] | None = None) -> Path:
        """The source, or a correctly named copy in ``folder`` if its extension is wrong or
        missing (converters rely on it). A password-protected Word, Excel or PowerPoint
        file is unlocked into ``folder`` (the job's private temporary folder) with its
        password from ``options["passwords"]`` ({file path: password})."""
        from . import office_password

        if self.src_fmt.id in office_password.CAN_UNLOCK and office_password.is_protected(
            self.source
        ):
            passwords = (options or {}).get("passwords") or {}
            password = passwords.get(str(self.source)) or passwords.get("*", "")
            return office_password.unlock_into(self.source, folder, password)
        if self.source.suffix.lower().lstrip(".") in self.src_fmt.extensions:
            return self.source
        copy = folder / f"source.{self.src_fmt.extension}"
        shutil.copyfile(self.source, copy)
        return copy

    def step_target(self, i: int, step_dir: Path) -> Path:
        """Where step ``i`` writes its result (the last step into an ``out`` subfolder)."""
        last = i == len(self.route) - 1
        ext = formats.FORMATS[self.route[i].dst].extension
        folder = step_dir / "out" if last else step_dir
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{self.stem if last else self.source.stem}.{ext}"


BAD_NAME_CHARS = '<>:"/\\|?*'
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{d}{n}" for d in ("COM", "LPT") for n in range(10)
}


def check_file_name(name: str, extension: str = "") -> str:
    """A name the user typed for the result, made safe: no folders, no forbidden characters.

    Returns the name without the extension (``extension`` is removed if the user typed it).
    """
    name = name.strip()
    if extension and name.lower().endswith(f".{extension.lower()}"):
        name = name[: -len(extension) - 1]
    name = name.rstrip(". ")
    if not name:
        raise ConversionError("Please enter a file name.")
    bad = sorted({c for c in name if c in BAD_NAME_CHARS or ord(c) < 32})
    if bad:
        shown = " ".join(c if ord(c) >= 32 else "?" for c in bad)
        raise ConversionError(f"A file name can't contain these characters: {shown}")
    if name.split(".")[0].upper() in RESERVED_NAMES:
        raise ConversionError(
            f'Windows doesn\'t allow the file name "{name}". Please choose another.'
        )
    return name


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
