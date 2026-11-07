# PyInstaller: pasta autocontida com o app (Python, PySide6, numpy, dados e ft8.dll). Uso: python installer/build.py
from pathlib import Path

root = Path(SPECPATH).parent  # noqa: F821  (SPECPATH é definido pelo PyInstaller)

a = Analysis(
    [str(root / "ic7300_station.py")],
    pathex=[str(root)],
    datas=[(str(root / "ic7300" / "data"), "ic7300/data"), (str(root / "ic7300" / "native" / "ft8.dll"), "ic7300/native")],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest", "ruff", "vulture", "PyInstaller",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
              "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="IC7300Station", console=False,
    icon=str(root / "installer" / "ic7300.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="IC7300Station")  # noqa: F821
