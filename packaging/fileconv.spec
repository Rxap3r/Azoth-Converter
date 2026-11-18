# PyInstaller spec: builds a folder with two programs that share one runtime:
#   FileConverter.exe  - the window (no console)
#   fileconv.exe       - the command-line tool
# Build with:  pyinstaller packaging/fileconv.spec --noconfirm
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

hiddenimports = collect_submodules("pdf2docx") + collect_submodules("fileconv")

# App resources (icon) plus package metadata, so the About window can show versions.
datas = [("../src/fileconv/resources", "fileconv/resources")]
for dist in ("PySide6-Essentials", "pillow", "pillow-heif", "PyMuPDF", "pdf2docx",
             "python-docx", "opencv-python-headless", "numpy"):
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
    name="FileConverter",
    console=False,
    icon="icon.ico",
    upx=False,
)
cli = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="fileconv",
    console=True,
    icon="icon.ico",
    upx=False,
)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="FileConverter", upx=False)
