"""Command-line interface.

Examples::

    azoth convert report.docx --to pdf
    azoth convert *.heic --to jpg -o converted
    azoth convert scan.pdf --to png --dpi 300
    azoth convert *.heic --to jpg --resize 2000
    azoth convert photo.jpg --to jpg --resize 50%
    azoth convert small.png --to png --resize 400% --ai
    azoth clean *.jpg -o to-share
    azoth clean --show photo.heic
    azoth formats report.pdf
    azoth pdf merge a.pdf b.pdf -o combined.pdf
    azoth pdf split big.pdf -o pages
    azoth pdf split big.pdf --ranges "1-3, 4-"
    azoth pdf edit scan.pdf --delete 2 --rotate 1=90
    azoth pdf compress big.pdf --level strong
    azoth pdf password add contract.pdf
    azoth password add budget.xlsx
    azoth pdf ocr scan.pdf --language deu
    azoth convert photo.jpg --to docx --language fra
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__, formats, quality, resize
from .converters import ConversionError
from .engine import Engine, unique_path
from .ocr import LANGUAGES


def _progress_printer(name: str):
    last = [-1]

    def show(fraction: float, message: str) -> None:
        pct = int(fraction * 100)
        if pct != last[0]:
            last[0] = pct
            print(f"\r  {name}: {pct:3d}% {message[:50]:<50}", end="", flush=True)

    return show


def _format_id(name: str) -> str | None:
    try:
        return formats.get(name).id
    except KeyError:
        return None


def cmd_convert(args: argparse.Namespace) -> int:
    from .converters import all_converters

    engine = Engine(all_converters(use_word=not args.no_word))
    if args.only_shrink and args.resize is None:
        print("--only-shrink needs --resize", file=sys.stderr)
        return 2
    if args.denoise and not args.ai:
        print("--denoise needs --ai", file=sys.stderr)
        return 2
    if args.shrink and _format_id(args.to) != "mp4":
        print("--shrink saves MP4: use --to mp4", file=sys.stderr)
        return 2
    if (args.tables_only or args.one_sheet) and _format_id(args.to) != "xlsx":
        print("--tables-only and --one-sheet are for PDF → Excel: use --to xlsx", file=sys.stderr)
        return 2
    if args.shrink and (args.resize or args.ai):
        print("--shrink is for videos; --resize and --ai are for pictures", file=sys.stderr)
        return 2
    if args.ai_best and not args.ai:
        print("--ai-best needs --ai", file=sys.stderr)
        return 2
    if args.ai_best and args.denoise:
        print("--denoise does not apply with --ai-best", file=sys.stderr)
        return 2
    try:
        size = None if args.resize is None else resize.parse(args.resize, not args.only_shrink)
        if args.ai:  # without --resize: same size, better quality
            size = replace(
                size or resize.Resize(resize.PERCENT, percent=100),
                ai=True,
                denoise=args.denoise or "medium",
                best=args.ai_best,
            )
    except resize.ResizeError as exc:
        print(exc, file=sys.stderr)
        return 2
    from . import upscale

    if args.ai and not upscale.available(args.ai_best):
        print("AI enhancement is not available because the AI model is missing.", file=sys.stderr)
        return 2
    options = {
        "resize": size,
        "shrink": args.shrink,
        "tables_only": args.tables_only,
        "one_sheet": args.one_sheet,
        "level": args.level,
        "quality": args.quality,
        "dpi": args.dpi,
        "keep_metadata": args.keep_metadata,
        "ocr": args.ocr,
        "ocr_language": args.language,
        "ocr_turn_pages": not args.keep_rotation,
    }
    failures = 0
    paths = [Path(f) for f in args.files]
    passwords = _ask_office_passwords(paths)
    if passwords is None:
        return 1
    options["passwords"] = passwords
    printers = [None if args.quiet else _progress_printer(p.name) for p in paths]
    current = [0]  # photos run in parallel: only show the progress of the file shown next

    def show(i: int, fraction: float, message: str) -> None:
        if i == current[0]:
            printers[i](fraction, message)

    results = engine.convert_many(
        paths,
        args.to,
        args.output,
        options=options,
        overwrite=args.overwrite,
        progress=None if args.quiet else show,
    )
    for i, outcome in results:
        current[0] = i + 1
        path = paths[i]
        if isinstance(outcome, ConversionError):
            failures += 1
            if not args.quiet:
                print()
            print(f"✗ {path.name}: {outcome}", file=sys.stderr)
            continue
        if isinstance(outcome, Exception):
            raise outcome
        if not args.quiet:
            print()
            for out in outcome.outputs:
                print(f"✓ {path.name} → {out}")
            for warning in outcome.warnings:
                print(f"  warning: {warning}")
            for note in outcome.notes:
                print(f"  note: {note}")
    return 1 if failures else 0


def cmd_clean(args: argparse.Namespace) -> int:
    from . import metadata

    failures = 0
    for file in args.files:
        path = Path(file)
        try:
            if args.show:
                found = metadata.inspect(path)
                print(f"{path.name}:" if found else f"{path.name}: no metadata found")
                for item in found:
                    print(f"  {item}")
                continue
            result = metadata.clean_file(path, args.output, overwrite=args.overwrite)
        except ConversionError as exc:
            failures += 1
            print(f"✗ {path.name}: {exc}", file=sys.stderr)
            continue
        if not args.quiet:
            removed = ", ".join(f.label for f in result.removed) or "nothing found"
            print(f"✓ {path.name} → {result.output}  (removed: {removed})")
    return 1 if failures else 0


def cmd_formats(args: argparse.Namespace) -> int:
    engine = Engine()
    if args.markdown:
        from .format_list import build_markdown

        text = build_markdown()
        Path(args.markdown).write_text(text, encoding="utf-8", newline="\n")
        print(f"✓ Wrote {args.markdown}")
        return 0
    if args.file:
        fmt = formats.detect(Path(args.file))
        if fmt is None:
            print(f"Azoth Converter does not know the file type of {args.file}.", file=sys.stderr)
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
    from . import pdf_tools

    src = Path(args.file)
    out_dir = Path(args.output) if args.output else pdf_tools.split_folder(src)
    try:
        groups = None
        if args.ranges:
            groups = pdf_tools.parse_ranges(args.ranges, pdf_tools.page_count(src))
        pages = pdf_tools.split(src, out_dir, groups, overwrite=args.overwrite)
    except ConversionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"✓ Split into {len(pages)} files in {out_dir}")
    return 0


def cmd_pdf_edit(args: argparse.Namespace) -> int:
    from . import pdf_tools

    src = Path(args.file)
    try:
        total = pdf_tools.page_count(src)
        if args.pages:
            order = [i for g in pdf_tools.parse_ranges(args.pages, total) for i in g]
        else:
            order = list(range(total))
        delete = set()
        if args.delete:
            delete = {i for g in pdf_tools.parse_ranges(args.delete, total) for i in g}
        turns: dict[int, int] = {}
        for item in args.rotate or []:
            page, _, degrees = item.partition("=")
            if not page.strip().isdigit() or degrees.strip() not in ("90", "180", "270", "-90"):
                raise ConversionError(
                    f"“{item}” is not correct. Use this format: page=degrees, for example 2=90 "
                    "(degrees: 90, 180 or 270)."
                )
            index = int(page) - 1
            if not 0 <= index < total:
                raise ConversionError(f"Page {page} is not in this PDF. The PDF has {total} pages.")
            turns[index] = (turns.get(index, 0) + int(degrees)) % 360
        pages = [pdf_tools.PageEdit(i, turns.get(i, 0)) for i in order if i not in delete]
        out = Path(args.output) if args.output else pdf_tools.edited_path(src)
        result = pdf_tools.edit_pages(src, out, pages, overwrite=args.overwrite)
    except ConversionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"✓ Saved {len(pages)} pages → {result}")
    return 0


def cmd_pdf_compress(args: argparse.Namespace) -> int:
    from . import pdf_tools

    src = Path(args.file)
    out = Path(args.output) if args.output else pdf_tools.compressed_path(src)
    try:
        before = src.stat().st_size
        result = pdf_tools.compress(src, out, args.level, overwrite=args.overwrite)
    except OSError as exc:
        print(f"✗ Cannot read {src.name} ({exc.strerror or exc}).", file=sys.stderr)
        return 1
    except ConversionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    after = result.stat().st_size
    saved = round(100 * (1 - after / before))
    size = pdf_tools.size_text
    print(f"✓ {size(before)} → {size(after)} ({saved}% smaller) → {result}")
    return 0


def cmd_pdf_ocr(args: argparse.Namespace) -> int:
    from . import ocr

    src = Path(args.file)
    out = Path(args.output) if args.output else ocr.searchable_path(src)
    try:
        result = ocr.make_searchable(
            src,
            out,
            args.language or ocr.default_language(),
            overwrite=args.overwrite,
            progress=_progress_printer(src.name),
            turn_pages=not args.keep_rotation,
        )
    except ConversionError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        return 1
    print(f"\n✓ {src.name} → {result}")
    return 0


def _ask_office_passwords(paths: list[Path]) -> dict[str, str] | None:
    """Ask for the password of each protected Word, Excel or PowerPoint file (only when
    typing is possible). None if the user cancelled. Passwords are never stored."""
    import getpass

    from . import office_password

    passwords: dict[str, str] = {}
    protected = [p for p in paths if p.is_file() and office_password.is_protected(p)]
    if not protected or not sys.stdin.isatty():
        return passwords  # without a password, the file fails with a clear message
    try:
        for path in protected:
            for _attempt in range(3):
                password = getpass.getpass(f"Password for {path.name}: ")
                try:
                    office_password.decrypt(path, password)
                except ConversionError as exc:
                    print(f"! {exc}", file=sys.stderr)
                    continue
                passwords[str(path)] = password
                break
    except (EOFError, KeyboardInterrupt):
        print("\n✗ Cancelled. Azoth Converter did not convert a file.", file=sys.stderr)
        return None
    return passwords


def cmd_pdf_password(args: argparse.Namespace) -> int:
    import getpass

    from . import office_password, pdf_tools

    src = Path(args.file)
    if office_password.file_kind(src) is not None:
        pdf_tools = office_password  # the same steps for Word, Excel and PowerPoint files
    try:
        password = getpass.getpass("Password: ")
        if args.action == "add":
            problem = pdf_tools.password_problem(password)
            if problem:
                raise ConversionError(problem)
            warning = pdf_tools.password_warning(password)
            if warning:
                print(f"! {warning}", file=sys.stderr)
            if getpass.getpass("Repeat password: ") != password:
                raise ConversionError(
                    "The two passwords are not the same. Azoth Converter did not save a file."
                )
            out = Path(args.output) if args.output else pdf_tools.protected_path(src)
            result = pdf_tools.add_password(src, out, password, overwrite=args.overwrite)
            note = " Keep the password safe: without it, nobody can open the file."
        else:
            out = Path(args.output) if args.output else pdf_tools.unlocked_path(src)
            result = pdf_tools.remove_password(src, out, password, overwrite=args.overwrite)
            note = ""
    except ConversionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n✗ Cancelled. Azoth Converter did not save a file.", file=sys.stderr)
        return 1
    print(f"✓ Saved {result}.{note}")
    return 0


def _bounded(low: int, high: int):
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{text!r} is not a number without decimals") from None
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"use a number from {low} to {high}")
        return value

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        # The packaged Windows program is azoth-terminal.exe; installed with pip: azoth.
        prog="azoth-terminal" if getattr(sys, "frozen", False) else "azoth",
        description="Offline file converter. Your files never leave this computer.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("convert", help="convert files to a different format")
    p.add_argument("files", nargs="+", help="files to convert")
    p.add_argument("--to", "-t", required=True, help="target format, for example pdf, docx, jpg")
    p.add_argument("--output", "-o", help="output folder (default: next to each file)")
    p.add_argument("--overwrite", action="store_true", help="replace output files that are there")
    p.add_argument(
        "--level",
        choices=[lv.id for lv in quality.LEVELS],
        default=quality.DEFAULT.id,
        help="quality level (default: maximum)",
    )
    p.add_argument(
        "--quality",
        type=_bounded(quality.MIN_IMAGE_QUALITY, quality.MAX_IMAGE_QUALITY),
        default=None,
        help=f"photo quality {quality.MIN_IMAGE_QUALITY}-{quality.MAX_IMAGE_QUALITY} "
        "(replaces the --level value)",
    )
    p.add_argument(
        "--dpi",
        type=_bounded(quality.MIN_DPI, quality.MAX_DPI),
        default=None,
        help=f"resolution for PDF → images, {quality.MIN_DPI}-{quality.MAX_DPI} "
        "(replaces the --level value)",
    )
    p.add_argument(
        "--resize",
        metavar="SIZE",
        help="new picture size. The proportions stay the same. 50%% (percentage), 2000 (longest "
        "side in pixels), 1920x1080 (screen size: the picture goes in this area, turned for "
        "portrait pictures), 1920x (width), x1080 (height). Smaller pictures become larger "
        "(smooth, with no new shapes). If the target format is the same as the format of "
        "the file (for example --to jpg for a JPG), the result is a copy in the new size",
    )
    p.add_argument(
        "--only-shrink",
        action="store_true",
        help="with --resize: do not make pictures larger if they are smaller than the size",
    )
    p.add_argument(
        "--ai",
        action="store_true",
        help="enhance pictures with AI (slow; on this computer only). When the AI makes a "
        "picture larger, it adds new shapes and texture that are not in the initial picture. "
        "The result looks sharp, but it is not fully correct. Without --resize, the size "
        "stays the same and the picture becomes sharper, with less noise and fewer JPEG "
        "blocks. Do not use for documents or ID photos",
    )
    p.add_argument(
        "--denoise",
        choices=resize.DENOISE_LEVELS,
        default=None,
        help="with --ai: how much noise and how many JPEG blocks the AI removes (default: medium)",
    )
    p.add_argument(
        "--ai-best",
        action="store_true",
        help="with --ai: use the larger AI model. Hair, fur and grass look better when "
        "small pictures become much larger. But it is approximately 15× slower (some minutes "
        "for each picture)",
    )
    p.add_argument(
        "--shrink",
        choices=tuple(quality.SHRINK_LEVELS),
        default=None,
        help="with --to mp4: save videos as a smaller MP4 copy, with the name "
        '"name (smaller).mp4", for e-mail and messengers. The number is the shorter side '
        "in pixels (1080 = Full HD, 720 = HD, 480). Azoth Converter does not make smaller "
        "videos larger. Lossy: the picture becomes less sharp",
    )
    p.add_argument(
        "--tables-only",
        action="store_true",
        help="PDF → Excel: only the tables, without the other text on the pages",
    )
    p.add_argument(
        "--one-sheet",
        action="store_true",
        help="PDF → Excel: all pages on one sheet, not one sheet for each page. With "
        "--tables-only, a table that continues on more than one page (for example a bank "
        "statement) becomes one table",
    )
    p.add_argument(
        "--keep-metadata",
        action="store_true",
        help="keep photo and video metadata (for privacy, Azoth Converter usually removes it)",
    )
    p.add_argument(
        "--ocr",
        action="store_true",
        help="images → PDF: recognise the text, so that you can search the PDF",
    )
    p.add_argument(
        "--language",
        choices=list(LANGUAGES),
        default=None,
        help="language of the text for text recognition (default: the language of the computer)",
    )
    p.add_argument(
        "--keep-rotation",
        action="store_true",
        help="with --ocr: do not turn pictures that are on their side or upside down",
    )
    p.add_argument(
        "--no-word",
        "--no-office",
        action="store_true",
        dest="no_word",
        help="use LibreOffice also when Microsoft Office (Word, Excel, PowerPoint) is installed",
    )
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser(
        "clean",
        help="remove metadata (location, camera, author, company …). The content does not change",
        description="Save a copy of each photo or document without its metadata. Photos: "
        "GPS location, camera, date, author, comments and preview pictures. PDF, DOCX, "
        "XLSX, PPTX: author, company, dates, edit history, earlier PDF versions; names on "
        "comments become 'Author'. The picture or text stays exactly the same; the "
        "original file is not changed.",
    )
    p.add_argument("files", nargs="+", help="photos, images, PDF, DOCX, XLSX or PPTX files")
    p.add_argument(
        "--output", "-o", help="output folder (default: next to each file, as 'name (clean)')"
    )
    p.add_argument("--overwrite", action="store_true", help="replace output files that are there")
    p.add_argument(
        "--show", action="store_true", help="only show the metadata. Do not change the file"
    )
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("formats", help="show the conversions that Azoth Converter can do")
    p.add_argument("file", nargs="?", help="show the target formats for this file")
    p.add_argument("--markdown", metavar="PATH", help="write the full table as Markdown")
    p.set_defaults(func=cmd_formats)

    pdf = sub.add_parser("pdf", help="PDF tools").add_subparsers(dest="pdf_cmd", required=True)
    p = pdf.add_parser("merge", help="put PDFs together into one PDF")
    p.add_argument("files", nargs="+")
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_pdf_merge)
    p = pdf.add_parser("split", help="save each page (or each range of pages) as a separate PDF")
    p.add_argument("file")
    p.add_argument("--output", "-o", help="output folder (default: name_pages next to the PDF)")
    p.add_argument(
        "--ranges", help='one PDF for each range, not for each page, for example "1-3, 5, 8-"'
    )
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_pdf_split)
    p = pdf.add_parser(
        "edit",
        help="save a copy with pages in a different sequence, turned or deleted (the quality stays "
        "the same)",
    )
    p.add_argument("file")
    p.add_argument(
        "--pages",
        help='new page sequence, for example "3, 1-2" (the copy does not have the pages that '
        "are not in the sequence)",
    )
    p.add_argument("--delete", help='pages to delete, for example "2, 5-6"')
    p.add_argument(
        "--rotate",
        action="append",
        metavar="PAGE=DEGREES",
        help="turn a page clockwise, for example 2=90",
    )
    p.add_argument("--output", "-o", help="output file (default: 'name (edited).pdf')")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_pdf_edit)
    p = pdf.add_parser(
        "compress", help="save a smaller copy (makes very sharp pictures less sharp)"
    )
    p.add_argument("file")
    p.add_argument(
        "--level",
        "-l",
        choices=[level.id for level in quality.COMPRESS_LEVELS],
        default=quality.DEFAULT_COMPRESS.id,
        help="light: the quality stays the same; balanced (default): pictures at 200 dpi; "
        "strong: pictures at 150 dpi JPG",
    )
    p.add_argument("--output", "-o", help="output file (default: 'name (compressed).pdf')")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_pdf_compress)
    p = pdf.add_parser("ocr", help="make a scanned PDF searchable (text recognition)")
    p.add_argument("file")
    p.add_argument(
        "--language",
        choices=list(LANGUAGES),
        default=None,
        help="language of the text for text recognition (default: the language of the computer)",
    )
    p.add_argument(
        "--keep-rotation",
        action="store_true",
        help="do not turn pages that are on their side or upside down",
    )
    p.add_argument("--output", "-o", help="output file (default: 'name (searchable).pdf')")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_pdf_ocr)
    p = pdf.add_parser(
        "password",
        help="add or remove a password on a PDF, or on a Word, Excel or PowerPoint file (you type "
        "the password; Azoth Converter does not keep it)",
    )
    p.add_argument("action", choices=["add", "remove"])
    p.add_argument("file")
    p.add_argument(
        "--output", "-o", help="output file (default: 'name (protected).pdf' / '(unlocked)')"
    )
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_pdf_password)
    p = sub.add_parser(
        "password",
        help="add or remove a password on a PDF, Word, Excel or PowerPoint file (the same as "
        "'azoth pdf password')",
    )
    p.add_argument("action", choices=["add", "remove"])
    p.add_argument("file")
    p.add_argument("--output", "-o", help="output file (default: 'name (protected)')")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_pdf_password)

    p = sub.add_parser("gui", help="open the app with windows and buttons")
    p.set_defaults(func=lambda a: __import__("azoth.gui.app", fromlist=["main"]).main())
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(errors="replace")  # Windows consoles: ✓/✗/→
            sys.stderr.reconfigure(errors="replace")
        except AttributeError:
            pass
    args = build_parser().parse_args(argv)
    if sys.platform == "win32" and isinstance(getattr(args, "files", None), list):
        args.files = expand_wildcards(args.files)
    return args.func(args)


def expand_wildcards(files: list[str]) -> list[str]:
    """Expand ``*.heic`` and ``photo?.jpg`` ourselves: on Linux and macOS the terminal does
    it, but Windows' Command Prompt and PowerShell pass the pattern on unchanged. A pattern
    that matches nothing stays as it is, so the user gets the usual "not found" message."""
    import glob

    result = []
    for name in files:
        matches = sorted(glob.glob(name)) if glob.has_magic(name) else []
        result.extend(matches or [name])
    return result


if __name__ == "__main__":
    sys.exit(main())
