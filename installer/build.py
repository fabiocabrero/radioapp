"""Gera o instalador: PyInstaller (pasta com o app) e Inno Setup (Setup.exe). Uso: python installer/build.py

Pré-requisitos: pip install pyinstaller; Inno Setup 6 (winget install JRSoftware.InnoSetup).
Os arquivos temporários ficam em %TEMP%\\ic7300_build (fora do OneDrive); o Setup.exe vai para installer/Output.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from ic7300 import __version__  # noqa: E402

work = Path(tempfile.gettempdir()) / "ic7300_build"
dist = work / "dist"
out = root / "installer" / "Output"
out.mkdir(parents=True, exist_ok=True)

subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(dist), "--workpath", str(work / "build"),
                str(root / "installer" / "ic7300.spec")], check=True, cwd=root)

candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
              Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
              Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe"]
iscc = next((p for p in candidates if p.exists()), None)
if not iscc:
    sys.exit("Inno Setup 6 não encontrado (winget install JRSoftware.InnoSetup).")
subprocess.run([str(iscc), f"/DSourceDir={dist / 'IC7300Station'}", f"/DAppVersion={__version__}", f"/DOutDir={out}",
                str(root / "installer" / "ic7300.iss")], check=True, cwd=root / "installer")
print("Instalador:", next(out.glob("IC7300Station-Setup-*.exe")))
