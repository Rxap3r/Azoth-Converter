"""The Explorer right-click menu: generated installer entries and the app side."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from azoth import context_menu, metadata
from azoth.context_menu import iss_text, menus
from azoth.gui import explorer

ISS = Path(__file__).parents[1] / "packaging" / "context_menu.iss"


def test_installer_entries_are_up_to_date():
    assert ISS.read_text(encoding="utf-8") == iss_text(), (
        "Run `python packaging/make_context_menu.py` and commit packaging/context_menu.iss"
    )


def test_installer_includes_the_menu_and_task():
    iss = (ISS.parent / "installer.iss").read_text(encoding="utf-8")
    assert '#include "context_menu.iss"' in iss
    assert f'Name: "{context_menu.TASK}"' in iss and "ChangesAssociations=yes" in iss


def test_menus_offer_the_most_useful_targets():
    all_menus = menus()
    labels = {ext: [e.label for e in entries] for ext, entries in all_menus.items()}
    assert labels[".docx"][0] == "To PDF"
    assert "To DOCX" in labels[".pdf"] and "Remove metadata" in labels[".pdf"]
    assert labels[".jpg"] == labels[".jpeg"] and "Remove metadata" in labels[".jpg"]
    assert "Remove metadata" not in labels[".doc"]
    for ext, entries in all_menus.items():
        assert entries[-1].target == explorer.OPEN, ext
        assert len(entries) <= context_menu.MAX_TARGETS + 2, ext
        assert len({e.key for e in entries}) == len(entries), ext
        assert [e.key for e in entries] == sorted(e.key for e in entries), ext  # menu order


def test_every_entry_is_a_real_conversion():
    from azoth import formats
    from azoth.converters import all_converters
    from azoth.engine import Engine

    engine = Engine(all_converters(), assume_available=True)
    by_ext = {f".{ext}": fmt for fmt in formats.FORMATS.values() for ext in fmt.extensions}
    for ext, entries in menus(engine).items():
        fmt = by_ext[ext]
        offered = {t.id for t in engine.targets_for(fmt.id)}
        for entry in entries:
            if entry.target == "clean":
                assert fmt.id in metadata.CLEANABLE
            elif entry.target != explorer.OPEN:
                assert entry.target in offered, (ext, entry.target)


def test_commands_start_the_app_with_the_file():
    text = iss_text()
    assert '"""{app}\\AzothConverter.exe"" --explorer pdf ""%1"""' in text
    # Every menu is removed before it is (re)created, and on uninstall.
    assert text.count("deletekey dontcreatekey uninsdeletekey") == len(menus())


# --- handing requests to one window ------------------------------------------------


@pytest.fixture
def storage(tmp_path, local_sockets):
    folder = tmp_path / "settings"
    folder.mkdir()
    return folder


def test_no_window_open_means_nothing_to_hand_over(storage):
    assert not explorer.forward("pdf", ["a.docx"], storage)


def test_requests_reach_the_open_window(storage):
    import threading

    listener = explorer.listen(storage)
    assert listener is not None
    got, arrived = [], threading.Event()

    def handle(target, files):
        got.append((target, files))
        arrived.set()

    server = explorer.Server(listener, handle)
    try:
        assert explorer.listen(storage) is None  # only one window collects requests
        assert explorer.forward("pdf", [r"C:\Docs\report.docx"], storage)
        assert arrived.wait(5)
        assert got == [("pdf", [r"C:\Docs\report.docx"])]
    finally:
        server.stop()


def test_programs_without_the_key_are_ignored(storage, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    listener = explorer.listen(storage)
    got = []
    server = explorer.Server(listener, lambda *r: got.append(r))
    try:
        (other / explorer.KEY_FILE).write_text("00" * 32)  # a different secret
        from multiprocessing.connection import Client

        with pytest.raises(Exception):  # noqa: B017 - authentication fails
            with Client(explorer.address(storage), authkey=b"\0" * 32) as conn:
                conn.send_bytes(b'{"to": "pdf", "files": ["x"]}')
        assert got == []
    finally:
        server.stop()


def test_key_stays_private(storage):
    key = explorer._key(storage)
    assert explorer._key(storage) == key and len(key) == 32
    if sys.platform != "win32":
        assert (storage / explorer.KEY_FILE).stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "message",
    [
        b"",
        b"not json",
        b"[]",
        b'{"to": 1, "files": ["a"]}',
        b'{"to": "pdf", "files": []}',
        b'{"to": "pdf", "files": "a"}',
        b'{"to": "pdf"}',
    ],
)
def test_bad_messages_are_ignored(message):
    assert explorer.parse(message) is None


def test_explorer_flag_opens_the_app(monkeypatch):
    import azoth.__main__ as entry
    import azoth.gui.app as app

    seen = []
    monkeypatch.setattr(app, "main", lambda explorer=None: seen.append(explorer) or 0)
    monkeypatch.setattr(sys, "argv", ["AzothConverter.exe", "--explorer", "pdf", "a.docx"])
    assert entry.main() == 0
    assert seen == [("pdf", ["a.docx"])]
