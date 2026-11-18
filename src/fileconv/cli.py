"""Command-line interface.

Examples::

    fileconv convert report.docx --to pdf
    fileconv convert *.heic --to jpg -o converted
    fileconv convert scan.pdf --to png --dpi 300
    fileconv formats report.pdf
    fileconv pdf merge a.pdf b.pdf -o combined.pdf
    fileconv pdf split big.pdf -o pages
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, formats
from .converters import ConversionError
from .engine import Engine, unique_path


def _progress_printer(name: str):
    last = [-1]

    def show(fraction: float, message: str) -> None:
        pct = int(fraction * 100)
        if pct != last[0]:
            last[0] = pct
            print(f"\r  {name}: {pct:3d}% {message[:50]:<50}", end="", flush=True)

    return show


def cmd_convert(args: argparse.Namespace) -> int:
    engine = Engine()
    options = {
        "quality": args.quality,
        "dpi": args.dpi,
        "keep_metadata": args.keep_metadata,
    }
    failures = 0
    for file in args.files:
        path = Path(file)
        try:
            result = engine.convert(
                path,
                args.to,
                args.output,
                options=options,
                overwrite=args.overwrite,
                progress=None if args.quiet else _progress_printer(path.name),
            )
        except ConversionError as exc:
            failures += 1
            if not args.quiet:
                print()
            print(f"✗ {path.name}: {exc}", file=sys.stderr)
            continue
        if not args.quiet:
            print()
            for out in result.outputs:
                print(f"✓ {path.name} → {out}")
            for note in result.notes:
                print(f"  note: {note}")
    return 1 if failures else 0


def cmd_formats(args: argparse.Namespace) -> int:
    engine = Engine()
    if args.markdown:
        from .format_list import build_markdown

        try:
            text = build_markdown(engine)
        except RuntimeError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 1
        Path(args.markdown).write_text(text, encoding="utf-8", newline="\n")
        print(f"✓ Wrote {args.markdown}")
        return 0
    if args.file:
        fmt = formats.detect(Path(args.file))
        if fmt is None:
            print(f"Unknown file type: {args.file}", file=sys.stderr)
            return 1
        print(f"{args.file} is {fmt.name}. It can be converted to:")
        for target in engine.targets_for(fmt.id):
            print(f"  {target.id:<6} {target.name}")
        return 0

    print("Supported formats (source → targets):")
    for fmt in formats.FORMATS.values():
        targets = engine.targets_for(fmt.id)
        if targets:
            print(f"  {fmt.id:<6} → {', '.join(t.id for t in targets)}")
    for conv in engine.unavailable():
        print(f"\nNot available: {conv.label}. {conv.unavailable_reason()}")
    return 0


def cmd_pdf_merge(args: argparse.Namespace) -> int:
    from .converters.pdf import merge_pdfs

    out = Path(args.output)
    if not args.overwrite:
        out = unique_path(out)
    try:
        merge_pdfs([Path(f) for f in args.files], out)
    except ConversionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"✓ Merged {len(args.files)} files → {out}")
    return 0


def cmd_pdf_split(args: argparse.Namespace) -> int:
    from .converters.pdf import split_pdf

    src = Path(args.file)
    out_dir = Path(args.output) if args.output else src.parent / f"{src.stem}_pages"
    if out_dir.exists() and any(out_dir.iterdir()) and not args.overwrite:
        out_dir = unique_path(out_dir)
    try:
        pages = split_pdf(src, out_dir)
    except ConversionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"✓ Split into {len(pages)} files in {out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fileconv",
        description="Offline file converter. Your files never leave this computer.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("convert", help="convert files to another format")
    p.add_argument("files", nargs="+", help="files to convert")
    p.add_argument("--to", "-t", required=True, help="target format, e.g. pdf, docx, jpg")
    p.add_argument("--output", "-o", help="output folder (default: next to each file)")
    p.add_argument("--overwrite", action="store_true", help="replace existing output files")
    p.add_argument("--quality", type=int, default=None, help="JPEG/WebP quality 1-100")
    p.add_argument("--dpi", type=int, default=None, help="resolution for PDF ↔ image")
    p.add_argument(
        "--keep-metadata",
        action="store_true",
        help="keep photo EXIF data (removed by default for privacy)",
    )
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("formats", help="list supported conversions")
    p.add_argument("file", nargs="?", help="show targets for this file")
    p.add_argument("--markdown", metavar="PATH", help="write the full list as Markdown")
    p.set_defaults(func=cmd_formats)

    pdf = sub.add_parser("pdf", help="PDF tools").add_subparsers(dest="pdf_cmd", required=True)
    p = pdf.add_parser("merge", help="join PDFs into one")
    p.add_argument("files", nargs="+")
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_pdf_merge)
    p = pdf.add_parser("split", help="save every page as its own PDF")
    p.add_argument("file")
    p.add_argument("--output", "-o", help="output folder")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_pdf_split)

    p = sub.add_parser("gui", help="open the graphical app")
    p.set_defaults(func=lambda a: __import__("fileconv.gui.app", fromlist=["main"]).main())
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(errors="replace")  # Windows consoles: ✓/✗/→
            sys.stderr.reconfigure(errors="replace")
        except AttributeError:
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
