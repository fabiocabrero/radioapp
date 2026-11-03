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


def list_output_devices() -> list[str]:
    try:
        import sounddevice as sd
    except Exception:
        return []
    seen, out = set(), []
    for d in sd.query_devices():
        if d["max_output_channels"] > 0 and d["name"] not in seen:
            seen.add(d["name"])
            out.append(d["name"])
    return out


def find_radio_output() -> str:
    return next((n for n in list_output_devices() if "USB Audio CODEC" in n), "")


# No Windows o mesmo dispositivo aparece em várias APIs de áudio; WASAPI (taxa nativa de 48 kHz do codec do IC-7300) tem preferência
_HOSTAPI_ORDER = ["Windows WASAPI", "Windows DirectSound", "MME", "Windows WDM-KS"]


def _norm(name: str) -> str:
    return "".join(name.lower().split())


def resolve_device(name: str, kind: str = "input") -> Optional[int]:
    """Índice do dispositivo cujo nome combina com `name` (as APIs truncam ou mudam espaços), na API preferida."""
    import sounddevice as sd

    if not name:
        return None
    wanted, field_name = _norm(name), f"max_{kind}_channels"
    apis = [a["name"] for a in sd.query_hostapis()]
    found: list[tuple[int, int]] = []
    for i, d in enumerate(sd.query_devices()):
        n = _norm(d["name"])
        if d[field_name] > 0 and (n == wanted or n.startswith(wanted) or wanted.startswith(n)):
            api = apis[d["hostapi"]]
            found.append((_HOSTAPI_ORDER.index(api) if api in _HOSTAPI_ORDER else 99, i))
    return min(found)[1] if found else None


def play_blocking(samples: np.ndarray, device: str) -> None:
    """Toca áudio (mono, 48 kHz) em estéreo no dispositivo e só retorna ao terminar."""
    import sounddevice as sd

    mono = samples.astype(np.float32)
    sd.play(np.column_stack([mono, mono]), FS, device=resolve_device(device, "output"))
    sd.wait()


def stop_playback() -> None:
    import sounddevice as sd

    sd.stop()


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
        self.device = device
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        def cb(indata, frames, time_info, status):
            self.on_samples(indata[:, 0].copy())

        index = resolve_device(self.device, "input")
        if index is None and self.device:
            raise RuntimeError(f"Dispositivo de áudio não encontrado: {self.device}")
        self._stream = sd.InputStream(device=index, channels=1, samplerate=FS, blocksize=2400, callback=cb)
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
        ft = self._ft8_demo()
        pos, block, emitted = 0, 2400, 0
        t0 = time.time()
        while not self._stop.is_set():
            idx = (np.arange(pos, pos + block)) % len(sig)
            chunk = sig[idx] + rng.normal(0, 0.02, block)
            if ft is not None:  # estações FT8 fictícias no início de cada slot de 15 s
                t = (t0 + emitted / FS) % 15 - 0.5
                if 0 <= t < len(ft) / FS:
                    seg = ft[int(t * FS):int(t * FS) + block]
                    chunk[:len(seg)] += seg
            self.on_samples(chunk.astype(np.float32))
            pos = (pos + block) % len(sig)
            emitted += block
            delay = t0 + emitted / FS - time.time()  # cadência exata de 48 kHz, como uma placa de som
            if delay > 0:
                time.sleep(delay)

    @staticmethod
    def _ft8_demo() -> Optional[np.ndarray]:
        from . import ft8
        from .ftengine import upsample4

        if not ft8.available():
            return None
        msgs = [("CQ DX W1AW FN31", 900), ("CQ JA1ABC PM95", 1450), ("CQ PY2XX GG66", 2050)]
        mix = sum(ft8.encode_message(m, "FT8", f) * 0.12 for m, f in msgs)
        return upsample4(mix)
