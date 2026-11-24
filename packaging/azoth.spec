# PyInstaller spec: builds a folder with two programs that share one runtime:
#   AzothConverter.exe  - the window (no console)
#   azoth-terminal.exe  - the command-line tool (typed commands; double-clicked: a note, then a Command Prompt)
# Build with:  pyinstaller packaging/azoth.spec --noconfirm
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

hiddenimports = (
    collect_submodules("pdf2docx") + collect_submodules("azoth") + collect_submodules("msoffcrypto")
)

import sys
from pathlib import Path

# The OCR language files must be there (python packaging/fetch_tessdata.py), or the
# app would ship without text recognition.
sys.path.insert(0, str(Path(SPECPATH)))
from fetch_tessdata import FILES, TARGET  # noqa: E402
from fetch_upscale_model import TARGET as AI_MODEL  # noqa: E402

missing = [name for name in FILES if not (TARGET / name).is_file()]
if missing:
    raise SystemExit(f"OCR language files missing: {missing}. Run python packaging/fetch_tessdata.py")
if not AI_MODEL.is_file():  # "Enhance with AI" needs it
    raise SystemExit(f"AI model missing: {AI_MODEL.name}. Run python packaging/fetch_tessdata.py")
from fetch_ffmpeg import EXE as FFMPEG  # noqa: E402

if sys.platform == "win32" and not FFMPEG.is_file():  # video and audio need it
    raise SystemExit("FFmpeg missing. Run python packaging/fetch_tessdata.py")

# App resources (icon, OCR languages) plus package metadata, so the About window can show versions.
datas = [("../src/azoth/resources", "azoth/resources")]
for dist in ("PySide6-Essentials", "pillow", "pillow-heif", "PyMuPDF", "pdf2docx",
             "python-docx", "opencv-python-headless", "numpy", "msoffcrypto-tool", "openpyxl", "et-xmlfile"):
    datas += copy_metadata(dist)

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    hiddenimports=hiddenimports,
    datas=datas,
    excludes=[
        "tkinter", "matplotlib", "IPython", "pytest", "onnxruntime",
        # Qt parts the app doesn't use (keeps the download smaller)
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtSql", "PySide6.QtTest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

gui = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="AzothConverter",
    console=False,
    icon="icon.ico",
    upx=False,
)
cli = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="azoth-terminal",
    console=True,
    icon="icon.ico",
    upx=False,
)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="AzothConverter", upx=False)
