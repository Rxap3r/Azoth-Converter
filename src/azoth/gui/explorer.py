"""The Windows Explorer right-click menu: "Convert with Azoth Converter → To PDF …".

The installer adds the menu (see ``context_menu.py`` and ``packaging/installer.iss``);
each entry starts ``AzothConverter.exe --explorer <target> <file>``. Explorer starts the
program once *per selected file*, so the first one opens the window and the others only
hand their file over to it and quit at once. They talk through a local named pipe
(a Unix socket elsewhere), which only programs of the same user can use: it is
protected by a random key kept in the app's settings folder. Nothing goes over the
network, and messages are plain JSON (never pickled code).

Files handed over within a moment of each other form one batch, converted together.
Requests that arrive while a batch is running wait for it to finish.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from multiprocessing.connection import Client, Listener
from pathlib import Path

OPEN = "open"  # "Open in Azoth Converter": add the files, start nothing
KEY_FILE = "explorer.key"
BATCH_DELAY_MS = 800  # Explorer starts one program per file: wait for the others
_MAX_MESSAGE = 1 << 20


def _storage() -> Path:
    from .settings import storage_dir

    return storage_dir()


def address(storage: Path | None = None) -> str:
    storage = storage or _storage()
    tag = hashlib.sha256(str(storage.resolve()).encode()).hexdigest()[:16]
    if sys.platform == "win32":
        return rf"\\.\pipe\AzothConverter-{tag}"
    return os.path.join(tempfile.gettempdir(), f"azoth-explorer-{tag}.sock")


def _key(storage: Path | None = None) -> bytes:
    """The shared secret: only programs that can read the user's settings folder know it."""
    path = (storage or _storage()) / KEY_FILE
    try:
        return bytes.fromhex(path.read_text().strip())
    except (OSError, ValueError):
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        path.write_text(key)
        if sys.platform != "win32":
            path.chmod(0o600)
        return bytes.fromhex(key)


def forward(target: str, files: list[str], storage: Path | None = None) -> bool:
    """Hand the request to a window that is already open. False if there is none."""
    _allow_window_to_come_forward()
    try:
        with Client(address(storage), authkey=_key(storage)) as conn:
            conn.send_bytes(json.dumps({"to": target, "files": files}).encode())
        return True
    except (OSError, EOFError, ValueError):
        return False
    except Exception:  # noqa: BLE001 - e.g. AuthenticationError: not our window
        return False


def _allow_window_to_come_forward() -> None:
    """Windows only lets the program the user just started bring a window to the front.
    That is this short-lived program (started by Explorer), so it passes the right on to
    the open window; otherwise the window would only blink in the taskbar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except (AttributeError, OSError):
        pass


def listen(storage: Path | None = None) -> Listener | None:
    """Become the window that collects requests. None if another program already is.

    On Windows the pipe can only be created once (the first program wins). Elsewhere
    a socket file left behind by a program that crashed is removed first."""
    addr = address(storage)
    try:
        return Listener(addr, authkey=_key(storage))
    except OSError:
        if sys.platform == "win32" or not _stale(addr):
            return None
    try:
        os.unlink(addr)
        return Listener(addr, authkey=_key(storage))
    except OSError:
        return None


def _stale(addr: str) -> bool:
    """True if nobody answers at the socket file ``addr`` any more."""
    import socket

    with socket.socket(socket.AF_UNIX) as sock:
        try:
            sock.connect(addr)
        except (ConnectionRefusedError, FileNotFoundError):
            return True
        except OSError:
            return False
    return False


def parse(message: bytes) -> tuple[str, list[str]] | None:
    """``(target, files)`` from a message, or None if it isn't a valid request."""
    try:
        data = json.loads(message.decode("utf-8"))
        target, files = data["to"], data["files"]
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if not isinstance(target, str) or not isinstance(files, list):
        return None
    files = [f for f in files if isinstance(f, str) and f]
    return (target, files) if files else None


class Server:
    """Accepts requests in a background thread; ``handle(target, files)`` is called for
    each valid one (from that thread: connect it to the window with a queued signal)."""

    def __init__(self, listener: Listener, handle) -> None:
        self.listener = listener
        self.handle = handle
        self._stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, name="explorer-requests", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stopped.set()
        try:
            self.listener.close()
        except OSError:
            pass

    def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                conn = self.listener.accept()
            except Exception:  # noqa: BLE001 - wrong key, a program that gave up, or closed
                if self._stopped.wait(0.05):
                    return
                continue
            try:
                with conn:
                    if conn.poll(5):
                        request = parse(conn.recv_bytes(_MAX_MESSAGE))
                        if request is not None:
                            self.handle(*request)
            except (OSError, EOFError):
                continue


def start(target: str, files: list[str]) -> Listener | None:
    """Hand the request over to an open window, or become that window: returns the
    listener to serve with, or None if the request was handed over."""
    for _ in range(25):  # a few seconds at most, while another program is starting
        if forward(target, files):
            return None
        listener = listen()
        if listener is not None:
            return listener
        time.sleep(0.2)
    raise RuntimeError("Azoth Converter is busy starting. Try again.")


# --- the window side (Qt) -------------------------------------------------------------


def attach(window, listener: Listener):
    """Let ``window`` (a MainWindow) receive requests; returns the controller."""
    from PySide6.QtCore import QObject, Qt, QTimer, Signal

    class Requests(QObject):
        received = Signal(str, list)

        def __init__(self) -> None:
            super().__init__(window)
            self.pending: list[tuple[str, list[Path]]] = []
            self.timer = QTimer(self, singleShot=True, interval=BATCH_DELAY_MS)
            self.timer.timeout.connect(self.run_next)
            self.received.connect(self.add)
            window.batch_finished.connect(self._after_batch)
            self.server = Server(listener, self.received.emit)
            window.destroyed.connect(self.close)

        def add(self, target: str, files: list) -> None:
            paths = [Path(f) for f in files]
            if self.pending and self.pending[-1][0] == target:
                self.pending[-1][1].extend(p for p in paths if p not in self.pending[-1][1])
            else:
                self.pending.append((target, paths))
            if not window.is_busy():
                self.timer.start()  # (re)starts: wait for the rest of the selection

        def _after_batch(self) -> None:
            if self.pending:
                self.timer.start()

        def run_next(self) -> None:
            if not self.pending or window.is_busy():
                return
            target, paths = self.pending.pop(0)
            window.run_explorer_request(target, paths)
            if window.windowState() & Qt.WindowState.WindowMinimized:
                window.showNormal()
            window.raise_()
            window.activateWindow()
            if self.pending and not window.is_busy():
                self.timer.start()

        def close(self, *_args) -> None:
            self.server.stop()

    return Requests()
