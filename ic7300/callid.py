"""Identificação de indicativo pela voz, sem internet.

Como funciona: o reconhecedor de fala offline Vosk (opcional, modelo pequeno baixado uma vez) recebe o áudio recebido
enquanto há voz e só pode "ouvir" palavras do alfabeto fonético e números (gramática fechada: bem mais preciso que fala
livre). O texto vira letras e dígitos, e o candidato é validado pelo prefixo no cty.dat (país existente) e pelo formato.

Limites reais: funciona com quem soletra devagar e com sinal razoável; em QRM, QSB forte ou fala corrida erra ou não
reconhece. A validação offline confirma que o PREFIXO existe, não que a licença exista. Sempre confirme de ouvido.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import applog
from .dxcc import Cty
from .settings import app_dir

LETTERS = {
    "alfa": "A", "alpha": "A", "bravo": "B", "charlie": "C", "charles": "C", "delta": "D", "echo": "E", "eco": "E",
    "foxtrot": "F", "fox": "F", "golf": "G", "hotel": "H", "india": "I", "juliet": "J", "juliett": "J",
    "kilo": "K", "lima": "L", "mike": "M", "november": "N", "oscar": "O", "papa": "P", "quebec": "Q", "romeo": "R",
    "romeu": "R", "sierra": "S", "tango": "T", "uniform": "U", "uniforme": "U", "victor": "V", "whiskey": "W",
    "whisky": "W", "xray": "X", "x-ray": "X", "yankee": "Y", "zulu": "Z",
}
DIGITS = {
    "zero": "0", "um": "1", "uma": "1", "one": "1", "dois": "2", "duas": "2", "two": "2", "três": "3", "tres": "3",
    "three": "3", "quatro": "4", "four": "4", "cinco": "5", "five": "5", "seis": "6", "six": "6", "sete": "7",
    "seven": "7", "oito": "8", "eight": "8", "nove": "9", "nine": "9", "niner": "9",
}
SLASH = {"barra": "/", "stroke": "/", "slash": "/", "portable": "/", "portátil": "/"}
# "X-ray" não existe no vocabulário do modelo: ele ouve "ex ray" ou "x ray" (normalizado para "xray" antes da análise)
VOCAB = sorted(set(LETTERS) | set(DIGITS) | set(SLASH) | {"x", "ex", "ray"})
_XRAY = re.compile(r"\b(?:ex|x)[ -]?ray\b")

# prefixo (1 a 3 caracteres) + dígito + sufixo de 1 a 4 letras, com /P, /M, /MM, /QRP ou prefixo de visitante opcionais
_PATTERN = re.compile(r"^(?:[A-Z0-9]{1,3}/)?[A-Z0-9]{1,3}[0-9][A-Z]{1,4}(?:/[A-Z0-9]{1,3})?$")


@dataclass
class Candidate:
    call: str
    country: str
    confidence: float   # 0 a 1
    heard: str          # texto reconhecido

    def label(self) -> str:
        return f"{self.call} ({self.country or 'prefixo desconhecido'}) · confiança {self.confidence:.0%}"


def tokens_to_calls(text: str) -> list[str]:
    """Extrai sequências de letras/dígitos falados que formam um indicativo plausível."""
    runs: list[str] = []
    cur = ""
    text = _XRAY.sub("xray", text.lower().strip())
    for tok in re.split(r"\s+", text):
        ch = LETTERS.get(tok) or DIGITS.get(tok) or SLASH.get(tok)
        if ch:
            cur += ch
        else:
            if cur:
                runs.append(cur)
            cur = ""
    if cur:
        runs.append(cur)
    return [r.strip("/") for r in runs if _PATTERN.match(r.strip("/"))]


def score(call: str, cty: Optional[Cty], votes: int = 1) -> Candidate:
    entity = cty.lookup(call) if cty else None
    conf = 0.35 + (0.35 if entity else 0.0) + min(0.3, 0.1 * (votes - 1))
    return Candidate(call, entity.name if entity else "", min(conf, 0.95), "")


# ------------------------------------------------------------------ modelo e reconhecedor
MODELS = {
    "en": ("vosk-model-small-en-us-0.15", "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"),
    "pt": ("vosk-model-small-pt-0.3", "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"),
}


def models_dir() -> Path:
    d = app_dir() / "modelos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_path(lang: str) -> Optional[Path]:
    p = models_dir() / MODELS[lang][0]
    return p if (p / "am").exists() or (p / "conf").exists() else None


def engine_available() -> bool:
    try:
        import vosk  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def download_model(lang: str, progress: Callable[[int], None] = lambda pct: None) -> Path:
    """Baixa e extrai o modelo pequeno do Vosk. Só deve ser chamado por ação explícita do usuário."""
    import urllib.request

    name, url = MODELS[lang]
    zpath = models_dir() / f"{name}.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "IC7300Station (+https://github.com/fabiocabrero/radioapp)"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(zpath, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if total:
                progress(int(got * 100 / total))
    with zipfile.ZipFile(zpath) as z:
        z.extractall(models_dir())
    zpath.unlink(missing_ok=True)
    return models_dir() / name


def to_16k(x: np.ndarray) -> bytes:
    """48 kHz float para 16 kHz int16 (média de 3 amostras como filtro simples antes de decimar)."""
    n = len(x) // 3 * 3
    y = x[:n].reshape(-1, 3).mean(axis=1)
    return (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()


class CallsignListener:
    """Recebe áudio enquanto há voz, reconhece palavras fonéticas e anuncia o indicativo mais provável."""

    def __init__(self, cty: Optional[Cty], on_candidate: Callable[[Candidate], None], lang: str = "en") -> None:
        self.cty, self.on_candidate, self.lang = cty, on_candidate, lang
        self.enabled = False
        self.status = ""
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=200)
        self._thread: Optional[threading.Thread] = None
        self._votes: Counter[str] = Counter()
        self._rec = None
        self._was_voice = False

    def start(self) -> None:
        if not engine_available():
            raise RuntimeError("O reconhecedor offline (vosk) não está instalado.")
        path = model_path(self.lang)
        if not path:
            raise RuntimeError("Falta baixar o modelo de voz (Fonia > Identificar indicativo).")
        import vosk

        vosk.SetLogLevel(-1)
        model = vosk.Model(str(path))
        words = [w for w in VOCAB if model.vosk_model_find_word(w) >= 0] if hasattr(model, "vosk_model_find_word") else VOCAB
        self._rec = vosk.KaldiRecognizer(model, 16000, json.dumps(words + ["[unk]"]))
        self._votes.clear()
        self.enabled = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.status = f"Escutando ({len(words)} palavras no vocabulário)"

    def stop(self) -> None:
        self.enabled = False
        self._q.put(None)

    def feed(self, x: np.ndarray, voice: bool) -> None:
        """Chamado pela thread de áudio: só enfileira, o reconhecimento roda em outra thread."""
        if not self.enabled:
            return
        if voice:
            try:
                self._q.put_nowait(to_16k(x))
            except queue.Full:
                pass
        elif self._was_voice:
            try:
                self._q.put_nowait(b"")  # fim da fala: fecha o resultado
            except queue.Full:
                pass
        self._was_voice = voice

    def handle_text(self, text: str, final: bool) -> None:
        for call in tokens_to_calls(text):
            self._votes[call] += 1 if final else 0
            cand = score(call, self.cty, max(1, self._votes[call]))
            cand.heard = text
            self.on_candidate(cand)

    def _run(self) -> None:
        rec = self._rec
        while self.enabled:
            data = self._q.get()
            if data is None:
                break
            try:
                if data == b"":
                    self.handle_text(json.loads(rec.FinalResult()).get("text", ""), True)
                elif rec.AcceptWaveform(data):
                    self.handle_text(json.loads(rec.Result()).get("text", ""), True)
                else:
                    self.handle_text(json.loads(rec.PartialResult()).get("partial", ""), False)
            except Exception as exc:  # noqa: BLE001
                applog.log.error("Identificação de indicativo: %s", exc)
