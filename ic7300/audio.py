"""Captura de áudio do rádio (codec USB do IC-7300) e fonte simulada."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import numpy as np

from .dsp.cw_decoder import text_to_morse_audio

FS = 48000


def list_input_devices() -> list[str]:
    try:
        import sounddevice as sd
    except Exception:
        return []
    seen, out = set(), []
    for d in sd.query_devices():
        if d["max_input_channels"] > 0 and d["name"] not in seen:
            seen.add(d["name"])
            out.append(d["name"])
    return out


def find_radio_input() -> str:
    """Procura o codec USB do IC-7300 (aparece como 'USB Audio CODEC')."""
    return next((n for n in list_input_devices() if "USB Audio CODEC" in n), "")


class AudioSource:
    def __init__(self, on_samples: Callable[[np.ndarray], None]) -> None:
        self.on_samples = on_samples

    def start(self) -> None: ...
    def stop(self) -> None: ...


class DeviceAudio(AudioSource):
    def __init__(self, device: str, on_samples: Callable[[np.ndarray], None]) -> None:
        super().__init__(on_samples)
        self.device = device or None
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        def cb(indata, frames, time_info, status):
            self.on_samples(indata[:, 0].copy())

        self._stream = sd.InputStream(device=self.device, channels=1, samplerate=FS, blocksize=2400, callback=cb)
        self._stream.start()

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class SimAudio(AudioSource):
    """Ruído com uma mensagem de CW em loop, para demonstração e testes."""

    MESSAGE = "CQ CQ DE PY2XX PY2XX K"

    def __init__(self, on_samples: Callable[[np.ndarray], None]) -> None:
        super().__init__(on_samples)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        rng = np.random.default_rng()
        sig = np.concatenate([text_to_morse_audio(self.MESSAGE, 18, 650, amp=0.25), np.zeros(FS * 2)])
        pos, block = 0, 2400
        while not self._stop.is_set():
            idx = (np.arange(pos, pos + block)) % len(sig)
            self.on_samples((sig[idx] + rng.normal(0, 0.02, block)).astype(np.float32))
            pos = (pos + block) % len(sig)
            time.sleep(block / FS)
