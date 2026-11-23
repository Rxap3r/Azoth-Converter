"""Show and remove the hidden information in PDF, Word, Excel and PowerPoint files.

What is removed (like Office's own "Document Inspector"):

* the file properties: author, "last saved by", company, manager, title, subject,
  keywords, dates, editing time, revision number, template, software, custom properties;
* Word's revision marks (``rsid``: which editing session wrote which text) and the path
  of the template it was made from; Excel's "saved in folder" path and cloud document id;
* the names of the people who wrote comments or tracked changes are replaced by
  "Author" (the comments and changes themselves stay: they are part of the content);
* in PDFs: the document information, XMP blocks (also on pictures and pages), private
  program data (``PieceInfo``) and earlier versions kept by incremental saves.

The content is never changed. Only the parts that hold metadata are rewritten; every
other part of the file is copied as it is. Before a cleaned file is saved, it is checked:
every changed part must still be valid XML with exactly the same text and structure
(only attributes and the metadata elements themselves may differ), every PDF page must
have exactly the same content stream and text, and the cleaned file is inspected again
for leftovers. If any check fails, nothing is written.

Old binary formats (DOC, XLS, PPT) aren't supported: convert them to DOCX, XLSX or
PPTX first. Password-protected files need their password removed first.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

import pymupdf

from .converters import ConversionError

OFFICE = ("docx", "xlsx", "pptx")
CLEANABLE = ("pdf", *OFFICE)

ANONYMOUS = "Author"  # what names of comment and change authors become
_ANONYMOUS = {ANONYMOUS, "A", ""}


# --- shared ---------------------------------------------------------------------------


def _finding(label: str, detail: str):
    from .metadata import Finding  # metadata imports this module

    return Finding(label, detail)


def _short(values, limit: int = 3) -> str:
    values = list(dict.fromkeys(v for v in values if v))
    text = ", ".join(values[:limit])
    return text + (f" and {len(values) - limit} more" if len(values) > limit else "")


def _pdf_date(value: str) -> str:
    """``D:20241103142500+01'00'`` → ``2024-11-03 14:25``."""
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?", value or "")
    if not m:
        return value
    y, mo, d, h, mi = m.groups()
    text = "-".join(p for p in (y, mo, d) if p)
    return f"{text} {h}:{mi}" if h and mi else text


def _xml_date(value: str) -> str:
    """``2024-11-03T14:25:00Z`` → ``2024-11-03 14:25``."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", value or "")
    return f"{m.group(1)} {m.group(2)}" if m else value


# --- Office (DOCX, XLSX, PPTX) ----------------------------------------------------------

_CORE_LABELS = {
    "creator": "Author",
    "lastModifiedBy": "Last saved by",
    "created": "Created",
    "modified": "Last saved",
    "lastPrinted": "Last printed",
    "title": "Title",
    "subject": "Subject",
    "keywords": "Keywords",
    "description": "Comments in the properties",
    "category": "Category",
    "contentStatus": "Status",
    "revision": "Revision number",
    "identifier": "Identifier",
    "version": "Version",
    "language": "Language",
}
_APP_LABELS = {
    "Company": "Company",
    "Manager": "Manager",
    "Template": "Template",
    "TotalTime": "Editing time",
    "HyperlinkBase": "Link base",
    "Application": "Software",
    "AppVersion": "Software version",
}
_DATES = {"created", "modified", "lastPrinted"}

_ATTR = r"""\s{name}\s*=\s*(?:"[^"]*"|'[^']*')"""


def _attr_values(data: bytes, name: str) -> list[str]:
    pattern = rf"""\s{name}\s*=\s*(?:"([^"]*)"|'([^']*)')""".encode()
    return [(a or b).decode("utf-8", "replace") for a, b in re.findall(pattern, data)]


def _set_attr(data: bytes, name: str, value: str) -> bytes:
    return re.sub(_ATTR.format(name=name).encode(), f' {name}="{value}"'.encode(), data)


def _drop_attr(data: bytes, name: str) -> bytes:
    return re.sub(_ATTR.format(name=name).encode(), b"", data)


def _drop_elements(data: bytes, names) -> bytes:
    for name in names:
        data = re.sub(
            rf"<(?:\w+:)?{name}\b(?:[^>]*/>|[^>]*>.*?</(?:\w+:)?{name}\s*>)".encode(),
            b"",
            data,
            flags=re.S,
        )
    return data


def _empty_root(data: bytes) -> bytes:
    """Keep the root element (with its namespaces) of a properties part, drop all
    that's inside it."""
    m = re.search(rb"<((?:\w+:)?\w+)\b[^>]*?(/?)>", re.sub(rb"<\?.*?\?>", b"", data, count=1))
    if m is None or m.group(2):
        return data  # already empty
    start = data.index(m.group(0)) + len(m.group(0))
    end = data.rindex(b"</" + m.group(1))
    return data[:start] + data[end:]


def _children(data: bytes) -> dict[str, str]:
    root = ET.fromstring(data)
    return {
        child.tag.rsplit("}", 1)[-1]: "".join(child.itertext()).strip()
        for child in root
        if "".join(child.itertext()).strip()
    }


def _abs_path(data: bytes) -> str:
    return next(iter(_attr_values(data, "url")), "") if b"absPath" in data else ""


def _office_parts(data: bytes) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            return infos, {i.filename: zf.read(i) for i in infos}
    except (zipfile.BadZipFile, OSError, KeyError, EOFError) as exc:
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # encrypted Office files are OLE
            raise ConversionError(
                "This file is protected with a password. Remove the password first "
                "(PDF tools → Password), then try again."
            ) from exc
        raise ConversionError(f"Could not read the file: {exc}") from exc


def _is_word_part(name: str) -> bool:
    return name.startswith("word/") and name.endswith(".xml")


def _office_inspect(parts: dict[str, bytes]) -> list:
    found = []
    try:
        if "docProps/core.xml" in parts:
            for key, value in _children(parts["docProps/core.xml"]).items():
                label = _CORE_LABELS.get(key, key)
                found.append(_finding(label, _xml_date(value) if key in _DATES else value))
        if "docProps/app.xml" in parts:
            app = _children(parts["docProps/app.xml"])
            for key, label in _APP_LABELS.items():
                if app.get(key):
                    detail = app[key] + (" minutes" if key == "TotalTime" else "")
                    found.append(_finding(label, detail))
        if "docProps/custom.xml" in parts:
            names = _attr_values(parts["docProps/custom.xml"], "name")
            if names:
                found.append(_finding("Custom properties", _short(names)))
    except ET.ParseError as exc:
        raise ConversionError(f"Could not read the file properties: {exc}") from exc

    people, sessions, template, folder, cloud, traces = [], set(), "", "", False, False
    for name, data in parts.items():
        if not name.endswith((".xml", ".rels")):
            continue
        if _is_word_part(name):
            sessions.update(re.findall(rb'\sw:rsid\w*="([0-9A-Fa-f]+)"', data))
            sessions.update(re.findall(rb'<w:rsid\w*\s+w:val="([0-9A-Fa-f]+)"', data))
            people += _attr_values(data, "w:author") + _attr_values(data, "w15:author")
            if b"presenceInfo" in data or _attr_values(data, "w:date"):
                traces = True  # sign-in ids or dates of comments and changes
        elif name == "word/_rels/settings.xml.rels":
            for target in _template_targets(data):
                if _base_name(target) != target:
                    template = target
        elif name == "xl/workbook.xml":
            folder = _abs_path(data)
            cloud = b"revisionPtr" in data and bool(_attr_values(data, "documentId"))
            people += _attr_values(data, "userName")
        elif name.startswith("xl/comments"):
            people += [
                a.decode("utf-8", "replace") for a in re.findall(rb"<author>(.*?)</author>", data)
            ]
        elif name.startswith(("xl/persons/", "xl/revisions/")) or name == "xl/usernames.xml":
            people += _attr_values(data, "displayName") + _attr_values(data, "userName")
        elif name in ("ppt/commentAuthors.xml", "ppt/authors.xml"):
            people += _attr_values(data, "name")
    if sessions:
        found.append(
            _finding("Edit history", f"revision marks from {len(sessions)} editing sessions")
        )
    named = [p for p in people if p not in _ANONYMOUS]
    if named:
        found.append(_finding("Names of reviewers", _short(named)))
    elif traces:
        found.append(_finding("Comments and changes", "dates and sign-in details of the authors"))
    if template:
        found.append(_finding("Template path", template))
    if folder:
        found.append(_finding("Saved in folder", folder))
    if cloud:
        found.append(_finding("Cloud document id", "links the file to its online copy"))
    return found


def _template_targets(rels: bytes) -> list[str]:
    targets = []
    for rel in re.findall(rb"<Relationship\b[^>]*>", rels):
        if b"attachedTemplate" in rel:
            targets += _attr_values(rel, "Target")
    return targets


def _base_name(target: str) -> str:
    return re.split(r"[\\/]", target)[-1]


def _clean_template_rels(rels: bytes) -> bytes:
    def fix(m: re.Match) -> bytes:
        rel = m.group(0)
        if b"attachedTemplate" not in rel:
            return rel
        for target in _attr_values(rel, "Target"):
            rel = _set_attr(rel, "Target", _base_name(target))
        return rel

    return re.sub(rb"<Relationship\b[^>]*>", fix, rels)


def _clean_part(name: str, data: bytes) -> bytes:
    if name in ("docProps/core.xml", "docProps/custom.xml"):
        return _empty_root(data)
    if name == "docProps/app.xml":
        return _drop_elements(data, _APP_LABELS)
    if name == "word/_rels/settings.xml.rels":
        return _clean_template_rels(data)
    if _is_word_part(name):
        data = re.sub(rb'\sw:rsid\w*="[0-9A-Fa-f]*"', b"", data)
        data = _drop_elements(data, ["rsids", "rsid"])  # settings; styles and numbering
        for attr in ("w:author", "w15:author"):
            data = _set_attr(data, attr, ANONYMOUS)
        data = _set_attr(data, "w:initials", "A")
        data = _drop_attr(data, "w:date")
        data = _drop_attr(data, "w16cex:dateUtc")
        return _drop_elements(data, ["presenceInfo"])
    if name == "xl/workbook.xml":
        data = re.sub(
            rb"<mc:AlternateContent\b(?:(?!</mc:AlternateContent>).)*?absPath"
            rb".*?</mc:AlternateContent>",
            b"",
            data,
            flags=re.S,
        )
        data = _drop_elements(data, ["absPath", "revisionPtr"])
        return _set_attr(data, "userName", ANONYMOUS)
    if name.startswith("xl/comments"):
        return re.sub(rb"<author>.*?</author>", f"<author>{ANONYMOUS}</author>".encode(), data)
    if name.startswith(("xl/persons/", "xl/revisions/")) or name == "xl/usernames.xml":
        for attr in ("displayName", "userName", "userId"):
            data = _set_attr(data, attr, ANONYMOUS)
        return _set_attr(data, "providerId", "None")
    if name in ("ppt/commentAuthors.xml", "ppt/authors.xml"):
        for attr in ("name", "userId"):
            data = _set_attr(data, attr, ANONYMOUS)
        data = _set_attr(data, "initials", "A")
        return _set_attr(data, "providerId", "None")
    return data


# Elements that cleaning may remove from a part; everything else must stay the same.
_REMOVABLE = {
    "xl/workbook.xml": {"AlternateContent", "Choice", "Fallback", "absPath", "revisionPtr"},
}
_PROPERTY_PARTS = {"docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"}


def _structure(name: str, data: bytes) -> list:
    removable = _REMOVABLE.get(name, set())
    if _is_word_part(name):
        removable = removable | {"rsids", "rsid", "rsidRoot", "presenceInfo"}
    out = []
    for el in ET.fromstring(data).iter():
        local = el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else el.tag
        if local in removable:
            continue
        text = el.text if local != "author" else None  # Excel comment authors become "Author"
        out.append((el.tag, _meaningful(text), _meaningful(el.tail)))
    return out


def _meaningful(text: str | None) -> str:
    """Whitespace between elements (indentation) means nothing in Office XML; text
    inside an element (``<w:t> a </w:t>``) is compared exactly."""
    return "" if text is None or not text.strip() else text


def _check_office(before: dict[str, bytes], after: dict[str, bytes]) -> None:
    for name, data in after.items():
        if data == before[name]:
            continue
        try:
            if name in _PROPERTY_PARTS:
                ET.fromstring(data)
            elif _structure(name, data) != _structure(name, before[name]):
                raise ConversionError(
                    f"Removing the metadata would change the content ({name}). Nothing was saved."
                )
        except ET.ParseError as exc:
            raise ConversionError(
                f"The metadata can't be removed safely from this file ({name}). Nothing was saved."
            ) from exc


def _office_clean(data: bytes) -> bytes:
    infos, parts = _office_parts(data)
    cleaned = {
        name: _clean_part(name, body) if name.endswith((".xml", ".rels")) else body
        for name, body in parts.items()
    }
    _check_office(parts, cleaned)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for info in infos:  # same order, names, dates and compression as before
            zf.writestr(info, cleaned[info.filename], compress_type=info.compress_type)
    return out.getvalue()


# --- PDF ------------------------------------------------------------------------------

_PDF_LABELS = {
    "author": "Author",
    "title": "Title",
    "subject": "Subject",
    "keywords": "Keywords",
    "creator": "Made with",
    "producer": "Software",
    "creationDate": "Created",
    "modDate": "Last saved",
}


def _open_pdf(data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open("pdf", data)
    except Exception as exc:
        raise ConversionError(f"Could not read the PDF: {exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise ConversionError(
            "This PDF is protected with a password. Remove the password first "
            "(PDF tools → Password), then try again."
        )
    return doc


def _annotations(doc: pymupdf.Document):
    for page in doc:
        yield from page.annots() or []


def _keys_with(doc: pymupdf.Document, key: str) -> list[int]:
    catalog = doc.pdf_catalog()
    found = []
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, key)[0] != "null":
                found.append(xref)
        except Exception:  # noqa: BLE001 - free or damaged object: nothing to clean
            continue
    return [x for x in found if not (key == "Metadata" and x == catalog)]


def _pdf_inspect(doc: pymupdf.Document) -> list:
    found = []
    info = doc.metadata or {}
    for key, label in _PDF_LABELS.items():
        value = (info.get(key) or "").strip()
        if value:
            found.append(_finding(label, _pdf_date(value) if key.endswith("Date") else value))
    if doc.get_xml_metadata().strip():
        found.append(_finding("XMP metadata", "a hidden block with author, dates and software"))
    if _keys_with(doc, "Metadata"):
        found.append(_finding("Hidden metadata", "on pictures or pages"))
    if _keys_with(doc, "PieceInfo"):
        found.append(_finding("Program data", "private data of the program that made the PDF"))
    if doc.version_count > 1:
        found.append(
            _finding("Earlier versions", f"{doc.version_count - 1} earlier saved version(s)")
        )
    names = [
        doc.xref_get_key(a.xref, "T")[1]
        for a in _annotations(doc)
        if doc.xref_get_key(a.xref, "T")[0] == "string"
    ]
    named = [n for n in names if n not in _ANONYMOUS]
    if named:
        found.append(_finding("Names of reviewers", _short(named)))
    return found


def _page_fingerprint(doc: pymupdf.Document) -> list[tuple[bytes, str]]:
    return [(page.read_contents(), page.get_text()) for page in doc]


def _pdf_clean(data: bytes) -> bytes:
    doc = _open_pdf(data)
    try:
        if doc.get_sigflags() > 0:
            raise ConversionError(
                "This PDF is digitally signed. Removing its metadata would break the "
                "signature, so nothing was saved."
            )
        before = _page_fingerprint(doc)
        doc.set_metadata({})
        doc.del_xml_metadata()
        for xref in _keys_with(doc, "Metadata"):
            doc.xref_set_key(xref, "Metadata", "null")
        for xref in _keys_with(doc, "PieceInfo"):
            doc.xref_set_key(xref, "PieceInfo", "null")
        for annot in _annotations(doc):
            if doc.xref_get_key(annot.xref, "T")[0] == "string":
                doc.xref_set_key(annot.xref, "T", pymupdf.get_pdf_str(ANONYMOUS))
        # A full rewrite drops earlier versions; garbage=1 drops the now unused objects
        # (old properties) without touching anything else. Restrictions are kept.
        cleaned = doc.tobytes(garbage=1, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"Could not remove the metadata: {exc}") from exc
    finally:
        doc.close()
    with _open_pdf(cleaned) as check:
        if check.page_count != len(before) or _page_fingerprint(check) != before:
            raise ConversionError(
                "Removing the metadata would change the pages. Nothing was saved."
            )
    return cleaned


# --- entry points (used by metadata.py) -------------------------------------------------


def inspect_bytes(fmt: str, data: bytes) -> list:
    if fmt == "pdf":
        with _open_pdf(data) as doc:
            return _pdf_inspect(doc)
    _, parts = _office_parts(data)
    return _office_inspect(parts)


def clean_bytes(fmt: str, data: bytes) -> bytes:
    return _pdf_clean(data) if fmt == "pdf" else _office_clean(data)
