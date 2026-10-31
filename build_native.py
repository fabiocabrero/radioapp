"""Compila ft8.dll (ft8_lib + wrapper) com `python -m ziglang cc`. Só o desenvolvedor precisa disto."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).parent / "native"
srcs = [str(p) for d in ("ft8_lib/ft8", "ft8_lib/common", "ft8_lib/fft") for p in sorted((root / d).glob("*.c"))]
srcs.append(str(root / "ft8wrap.c"))
out = Path(__file__).parent / "ic7300" / "native" / "ft8.dll"
out.parent.mkdir(parents=True, exist_ok=True)
cmd = [sys.executable, "-m", "ziglang", "cc", "-shared", "-O2", "-target", "x86_64-windows-gnu",
       "-include", str(root / "compat.h"), "-I", str(root), "-I", str(root / "ft8_lib"), "-o", str(out), *srcs]
subprocess.run(cmd, check=True)
print("gerado:", out, out.stat().st_size, "bytes")
