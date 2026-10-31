"""FT8/FT4: decodificação e geração de áudio via ft8_lib (ft8.dll, ctypes)."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

SAMPLE_RATE = 12000
SLOT_SECONDS = {"FT8": 15.0, "FT4": 7.5}
_DLL = Path(__file__).parent / "native" / "ft8.dll"
_lib: Optional[ctypes.CDLL] = None


def available() -> bool:
    return _DLL.exists()


def _load() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(str(_DLL))
        lib.ftx_decode_slot.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_char_p, ctypes.c_int]
        lib.ftx_decode_slot.restype = ctypes.c_int
        lib.ftx_encode_message.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_float, ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_float), ctypes.c_int]
        lib.ftx_encode_message.restype = ctypes.c_int
        _lib = lib
    return _lib


@dataclass
class Decode:
    snr: int
    dt: float
    freq: int
    text: str

    def callsigns(self) -> list[str]:
        words = [w.strip("<>") for w in self.text.split()]
        return [w for w in words if any(c.isdigit() for c in w) and any(c.isalpha() for c in w) and len(w) >= 3
                and not (len(w) == 4 and w[:2].isalpha() and w[2:].isdigit())]


def decode_slot(samples: np.ndarray, mode: str = "FT8", sample_rate: int = SAMPLE_RATE) -> list[Decode]:
    """Decodifica um slot completo (mono, -1..1, 12 kHz)."""
    buf = np.ascontiguousarray(samples, dtype=np.float32)
    out = ctypes.create_string_buffer(8192)
    _load().ftx_decode_slot(buf.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(buf), sample_rate,
                            1 if mode == "FT4" else 0, out, len(out))
    results = []
    for line in out.value.decode("latin-1").splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            results.append(Decode(int(parts[0]), float(parts[1]), int(parts[2]), parts[3].strip()))
    return results


def encode_message(text: str, mode: str = "FT8", freq: float = 1500.0, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Áudio (float32, 12 kHz) da mensagem; levanta ValueError se não puder ser codificada."""
    out = (ctypes.c_float * (sample_rate * 15))()
    n = _load().ftx_encode_message(text.encode("ascii", "ignore"), 1 if mode == "FT4" else 0, freq, sample_rate,
                                   out, len(out))
    if n < 0:
        raise ValueError(f"Mensagem inválida para {mode}: {text!r}")
    return np.frombuffer(out, dtype=np.float32, count=n).copy()
