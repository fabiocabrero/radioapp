"""Fonia: gravação das conversas, mensagens gravadas (voz e CW), chamadas automáticas com escuta do canal e voz ao vivo com efeitos."""
from __future__ import annotations

import json
import threading
import time
import uuid
import wave
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import applog
from .audio import FS, resolve_device
from .dsp.voicefx import FxSettings, VoiceFX, process_all
from .settings import app_dir


def recordings_dir() -> Path:
    d = app_dir() / "gravacoes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def messages_dir() -> Path:
    d = app_dir() / "mensagens"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767.0
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels())[:, 0]
        return data


# ------------------------------------------------------------------ gravação das conversas
class ConversationRecorder:
    """Grava o áudio recebido em WAV. Modos: desligado, manual (botão REC) e automático (só quando há voz)."""

    PRE_S, TAIL_S, MIN_S = 1.5, 4.0, 1.5

    def __init__(self, on_saved: Optional[Callable[[Path, float], None]] = None) -> None:
        self.on_saved = on_saved
        self.mode = "off"
        self.label = ""
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._pre: deque[np.ndarray] = deque()
        self._pre_len = 0
        self._recording = False
        self._silent_s = 0.0
        self._started = 0.0

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def seconds(self) -> float:
        return (sum(len(c) for c in self._chunks) / FS) if self._recording else 0.0

    def set_mode(self, mode: str) -> None:
        with self._lock:
            if mode == self.mode:
                return
            if self._recording:
                self._finish_locked()
            self.mode = mode
            if mode == "manual":
                self._begin_locked()

    def feed(self, x: np.ndarray, voice: bool) -> None:
        with self._lock:
            if self.mode == "manual":
                self._chunks.append(x.copy())
            elif self.mode == "auto":
                dur = len(x) / FS
                if voice:
                    if not self._recording:
                        self._begin_locked()
                        self._chunks = list(self._pre)
                        self._pre.clear()
                        self._pre_len = 0
                    self._silent_s = 0.0
                if self._recording:
                    self._chunks.append(x.copy())
                    if not voice:
                        self._silent_s += dur
                        if self._silent_s >= self.TAIL_S:
                            self._finish_locked()
                else:
                    self._pre.append(x.copy())
                    self._pre_len += len(x)
                    while self._pre_len > self.PRE_S * FS and self._pre:
                        self._pre_len -= len(self._pre.popleft())

    def _begin_locked(self) -> None:
        self._recording = True
        self._chunks = []
        self._silent_s = 0.0
        self._started = time.time()

    def _finish_locked(self) -> None:
        self._recording = False
        data = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
        self._chunks = []
        secs = len(data) / FS
        if secs < self.MIN_S:
            return
        stamp = datetime.fromtimestamp(self._started).strftime("%Y%m%d_%H%M%S")
        name = f"{stamp}{('_' + self.label) if self.label else ''}.wav"
        path = recordings_dir() / name
        write_wav(path, data)
        applog.log.info("Gravação salva: %s (%.0f s)", path.name, secs)
        if self.on_saved:
            self.on_saved(path, secs)

    def stop(self) -> None:
        self.set_mode("off")


# ------------------------------------------------------------------ mensagens gravadas
@dataclass
class Message:
    id: str
    kind: str      # "voz" ou "cw"
    name: str
    text: str = ""   # CW: o texto; voz: observação
    file: str = ""   # voz: nome do WAV na pasta de mensagens


class MessageStore:
    def __init__(self) -> None:
        self.path = messages_dir() / "mensagens.json"
        self.items: list[Message] = []
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [Message(**m) for m in raw]
        except (OSError, ValueError, TypeError):
            self.items = []

    def save(self) -> None:
        self.path.write_text(json.dumps([asdict(m) for m in self.items], indent=1, ensure_ascii=False), encoding="utf-8")

    def add_voice(self, name: str, samples: np.ndarray, note: str = "") -> Message:
        mid = uuid.uuid4().hex[:8]
        fname = f"{mid}.wav"
        write_wav(messages_dir() / fname, samples)
        msg = Message(mid, "voz", name, note, fname)
        self.items.append(msg)
        self.save()
        return msg

    def add_cw(self, name: str, text: str) -> Message:
        msg = Message(uuid.uuid4().hex[:8], "cw", name, text.upper())
        self.items.append(msg)
        self.save()
        return msg

    def remove(self, mid: str) -> None:
        for m in list(self.items):
            if m.id == mid:
                if m.file:
                    try:
                        (messages_dir() / m.file).unlink()
                    except OSError:
                        pass
                self.items.remove(m)
        self.save()

    def get(self, mid: str) -> Optional[Message]:
        return next((m for m in self.items if m.id == mid), None)

    def samples(self, msg: Message) -> np.ndarray:
        return read_wav(messages_dir() / msg.file)


def cw_duration_s(text: str, wpm: int) -> float:
    """Duração aproximada de um texto em CW (palavra PARIS = 50 unidades)."""
    from .dsp.cw_decoder import TEXT_TO_MORSE

    units = 0
    for ch in text.upper():
        if ch == " ":
            units += 4  # soma-se ao espaço entre letras já contado
        elif ch in TEXT_TO_MORSE:
            code = TEXT_TO_MORSE[ch]
            units += sum(1 if s == "." else 3 for s in code) + (len(code) - 1) + 3
    return units * 1.2 / max(5, wpm)


# ------------------------------------------------------------------ chamadas automáticas
@dataclass
class CallPlan:
    gap_s: float = 20.0          # tempo entre o fim de uma chamada e o início da próxima (escuta)
    clear_s: float = 3.0         # canal livre exigido antes de chamar
    max_calls: int = 0           # 0 = até parar
    end_on_voice: bool = True    # encerra tudo ao detectar voz; senão só interrompe a chamada e espera o canal ficar livre
    abort_on_rx_voice: bool = True   # durante a chamada, voz no receptor interrompe
    abort_on_mic_voice: bool = True  # durante a chamada, voz no microfone do operador interrompe
    wpm: int = 20


class AutoCaller:
    """Repete uma mensagem (voz ou CW) com intervalo regulável, escutando o canal entre uma chamada e outra."""

    def __init__(self, ptt: Callable[[bool], None], play: Callable[[np.ndarray, Callable[[], bool]], bool],
                 send_cw: Callable[[str], None], stop_cw: Callable[[], None], rx_busy: Callable[[], bool],
                 mic_busy: Callable[[], bool], notify: Callable[[str], None], on_done: Callable[[], None] = lambda: None,
                 op_ptt: Callable[[], bool] = lambda: False, on_suspended: Callable[[str], None] = lambda reason: None) -> None:
        self.ptt, self.play, self.send_cw, self.stop_cw = ptt, play, send_cw, stop_cw
        self.rx_busy, self.mic_busy, self.notify, self.on_done = rx_busy, mic_busy, notify, on_done
        self.op_ptt, self.on_suspended = op_ptt, on_suspended  # PTT do operador (PC ou rádio) e aviso de suspensão
        self._paused = False
        self._resume = threading.Event()
        self._own_tx = False
        self._own_tx_until = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.calls = 0
        self.running = False

    def start(self, msg: Message, samples: Optional[np.ndarray], plan: CallPlan) -> None:
        self.stop()
        self._stop.clear()
        self._paused = False
        self._resume.clear()
        self.calls = 0
        self.running = True
        self._thread = threading.Thread(target=self._run, args=(msg, samples, plan), daemon=True)
        self._thread.start()

    def is_own_tx(self) -> bool:
        """True durante a transmissão do próprio app (e 1 s depois, pela demora da leitura do PTT no rádio)."""
        return self._own_tx or time.time() < self._own_tx_until

    @property
    def paused(self) -> bool:
        return self._paused

    def suspend(self, reason: str) -> None:
        """O operador acionou o PTT: interrompe a transmissão em curso e espera a decisão de retomar."""
        if not self.running or self._paused:
            return
        self._paused = True
        self._resume.clear()
        self.notify(f"Suspenso: {reason}")
        self.on_suspended(reason)

    def resume(self) -> None:
        self._paused = False
        self._resume.set()

    def _block_if_paused(self) -> None:
        while self._paused and not self._stop.is_set():
            self._resume.wait(0.1)

    def stop(self) -> None:
        self._stop.set()
        self._paused = False
        self._resume.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=3)

    def _sleep(self, s: float) -> None:
        self._stop.wait(s)

    def _abort_tx(self, plan: CallPlan) -> bool:
        return self._stop.is_set() or self._paused or (plan.abort_on_mic_voice and self.mic_busy()) or (plan.abort_on_rx_voice and self.rx_busy())

    def _wait_clear(self, plan: CallPlan) -> bool:
        """Espera o canal ficar livre por `clear_s` (e o operador soltar o PTT). Retorna False se deve encerrar."""
        free_since: Optional[float] = None
        warned = False
        while not self._stop.is_set():
            self._block_if_paused()
            if self.op_ptt():
                free_since = None  # o operador está transmitindo: não chama por cima
            elif self.rx_busy():
                if plan.end_on_voice:
                    self.notify("Voz detectada no canal: chamadas encerradas.")
                    return False
                free_since = None
                if not warned:
                    self.notify("Canal ocupado: aguardando ficar livre...")
                    warned = True
            else:
                free_since = free_since or time.time()
                if time.time() - free_since >= plan.clear_s:
                    return True
                self.notify(f"Verificando canal livre ({plan.clear_s - (time.time() - free_since):.0f} s)...")
            self._sleep(0.1)
        return False

    def _transmit(self, msg: Message, samples: Optional[np.ndarray], plan: CallPlan) -> bool:
        """Transmite uma vez. Retorna True se foi até o fim, False se interrompida."""
        self._own_tx = True
        try:
            if msg.kind == "cw":
                self.send_cw(msg.text)
                end = time.time() + cw_duration_s(msg.text, plan.wpm) + 0.5
                while time.time() < end:
                    if self._abort_tx(plan):
                        self.stop_cw()
                        return False
                    self._sleep(0.05)
                return True
            self.ptt(True)
            try:
                self._sleep(0.15)  # tempo do relé do rádio antes do áudio
                return bool(self.play(samples if samples is not None else np.zeros(0, np.float32), lambda: self._abort_tx(plan)))
            finally:
                self.ptt(False)
        finally:
            self._own_tx = False
            self._own_tx_until = time.time() + 1.0

    def _run(self, msg: Message, samples: Optional[np.ndarray], plan: CallPlan) -> None:
        try:
            while not self._stop.is_set():
                if not self._wait_clear(plan):
                    break
                self.notify(f"Transmitindo chamada {self.calls + 1}...")
                completed = self._transmit(msg, samples, plan)
                self.calls += 1
                if not completed:
                    if self._stop.is_set():
                        break
                    if self._paused:  # o operador assumiu: espera a decisão
                        self._block_if_paused()
                        continue
                    self.notify("Voz detectada: transmissão interrompida.")
                    if plan.end_on_voice:
                        break
                    continue
                if plan.max_calls and self.calls >= plan.max_calls:
                    self.notify(f"Concluído: {self.calls} chamadas.")
                    break
                end = time.time() + plan.gap_s
                while not self._stop.is_set() and time.time() < end:
                    if self._paused:
                        self._block_if_paused()
                        break  # ao retomar, volta a checar o canal e chama
                    if plan.end_on_voice and self.rx_busy():
                        self.notify("Resposta detectada (voz no canal): chamadas encerradas.")
                        self._stop.set()
                        break
                    self.notify(f"Escutando... próxima chamada em {max(0, end - time.time()):.0f} s ({self.calls} feitas)")
                    self._sleep(0.2)
        except Exception as exc:  # noqa: BLE001 (thread de fundo: registra e solta o PTT)
            applog.log.error("Chamada automática: %s", exc, exc_info=True)
            self.notify(f"Erro: {exc}")
        finally:
            try:
                self.ptt(False)
            except Exception:  # noqa: BLE001
                pass
            self.running = False
            self.on_done()


# ------------------------------------------------------------------ voz ao vivo com efeitos
class LiveVoice:
    """Microfone do PC com efeitos, para fones (teste) ou para o rádio (TX). O PTT é de quem chama."""

    def __init__(self, on_levels: Callable[[float, float, float], None] = lambda a, b, c: None) -> None:
        self.fx = VoiceFX()
        self.on_levels = on_levels
        self._in = self._out = None
        self._q: deque[np.ndarray] = deque(maxlen=20)
        self.running = False
        self.gain = 1.0
        self.mic_voice = False
        self._vad = None

    def start(self, mic: str, out: str, settings: FxSettings) -> None:
        import sounddevice as sd

        from .dsp.vad import VoiceDetector

        self.stop()
        self.fx.configure(settings)
        self.fx.reset()
        self._vad = VoiceDetector(margin_db=12.0, hang_s=0.6)
        i_dev, o_dev = resolve_device(mic, "input"), resolve_device(out, "output")
        if i_dev is None and mic:
            raise RuntimeError(f"Microfone não encontrado: {mic}")
        if o_dev is None and out:
            raise RuntimeError(f"Saída não encontrada: {out}")

        def cb_in(indata, frames, time_info, status):
            x = indata[:, 0].copy()
            if self._vad:
                self.mic_voice = self._vad.feed(x)
            y = self.fx.process(x * self.gain)
            self._q.append(y)
            self.on_levels(self.fx.in_db, self.fx.out_db, self.fx.gr_db)

        def cb_out(outdata, frames, time_info, status):
            try:
                y = self._q.popleft()
            except IndexError:
                outdata[:] = 0
                return
            n = min(frames, len(y))
            outdata[:n, 0] = y[:n]
            outdata[:n, 1] = y[:n]
            outdata[n:] = 0

        self._out = sd.OutputStream(device=o_dev, channels=2, samplerate=FS, blocksize=2400, callback=cb_out)
        self._in = sd.InputStream(device=i_dev, channels=1, samplerate=FS, blocksize=2400, callback=cb_in)
        self._out.start()
        self._in.start()
        self.running = True

    def stop(self) -> None:
        for s in (self._in, self._out):
            if s is not None:
                try:
                    s.stop()
                    s.close()
                except Exception:  # noqa: BLE001
                    pass
        self._in = self._out = None
        self._q.clear()
        self.running = False
        self.mic_voice = False


class MicCapture:
    """Grava um trecho do microfone (para mensagens de voz)."""

    def __init__(self) -> None:
        self._stream = None
        self._chunks: list[np.ndarray] = []

    def start(self, mic: str) -> None:
        import sounddevice as sd

        dev = resolve_device(mic, "input")
        if dev is None and mic:
            raise RuntimeError(f"Microfone não encontrado: {mic}")
        self._chunks = []
        self._stream = sd.InputStream(device=dev, channels=1, samplerate=FS, blocksize=2400,
                                      callback=lambda indata, f, t, s: self._chunks.append(indata[:, 0].copy()))
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        return np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)


def prepare_for_tx(samples: np.ndarray, settings: FxSettings) -> np.ndarray:
    """Aplica os efeitos de TX à mensagem gravada e normaliza o pico em 0,85."""
    y = process_all(samples, settings)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    return (y * (0.85 / peak)).astype(np.float32) if peak > 0 else y


class MicWatcher:
    """Escuta o microfone do operador só para saber se ele está falando (interrompe as chamadas automáticas)."""

    def __init__(self) -> None:
        self._stream = None
        self.voice = False

    def start(self, mic: str) -> None:
        import sounddevice as sd

        from .dsp.vad import VoiceDetector

        self.stop()
        vad = VoiceDetector(margin_db=12.0, hang_s=0.5)
        dev = resolve_device(mic, "input")

        def cb(indata, frames, time_info, status):
            self.voice = vad.feed(indata[:, 0])

        self._stream = sd.InputStream(device=dev, channels=1, samplerate=FS, blocksize=2400, callback=cb)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
        self._stream = None
        self.voice = False


class RxMonitor:
    """Toca o áudio recebido, já com os efeitos, em alto-falantes ou fones do PC (nunca no codec do rádio)."""

    def __init__(self) -> None:
        self._out = None
        self._q: deque[np.ndarray] = deque(maxlen=12)
        self.volume = 0.8
        self.running = False

    def start(self, device: str) -> None:
        import sounddevice as sd

        self.stop()
        dev = resolve_device(device, "output")
        if dev is None and device:
            raise RuntimeError(f"Saída não encontrada: {device}")

        def cb(outdata, frames, time_info, status):
            try:
                y = self._q.popleft() * self.volume
            except IndexError:
                outdata[:] = 0
                return
            n = min(frames, len(y))
            outdata[:n, 0] = y[:n]
            outdata[:n, 1] = y[:n]
            outdata[n:] = 0

        self._out = sd.OutputStream(device=dev, channels=2, samplerate=FS, blocksize=2400, callback=cb)
        self._out.start()
        self.running = True

    def push(self, y: np.ndarray) -> None:
        if self.running:
            self._q.append(y)

    def stop(self) -> None:
        if self._out is not None:
            try:
                self._out.stop()
                self._out.close()
            except Exception:  # noqa: BLE001
                pass
        self._out = None
        self._q.clear()
        self.running = False
