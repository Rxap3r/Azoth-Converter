# PyInstaller spec: builds a folder with two programs that share one runtime:
#   FileConverter.exe  - the window (no console)
#   fileconv.exe       - the command-line tool
# Build with:  pyinstaller packaging/fileconv.spec --noconfirm
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("pdf2docx") + collect_submodules("fileconv")

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    hiddenimports=hiddenimports,
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
    upx=False,
)
cli = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="fileconv",
    console=True,
    upx=False,
)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="FileConverter", upx=False)
