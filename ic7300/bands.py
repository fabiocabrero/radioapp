"""Planos de bandas por país/região, classes de licença, frequências de modos digitais e sugestão de modo."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .settings import app_dir

DATA = Path(__file__).parent / "data"

# Cor de cada uso no plano de bandas (RGB)
USE_COLORS = {"CW": (230, 160, 40), "DIG": (60, 170, 230), "SSB": (90, 200, 120), "FM": (200, 100, 200),
              "BCN": (230, 80, 80), "ALL": (150, 150, 150), "REP": (170, 90, 60)}
USE_LABELS = {"CW": "CW", "DIG": "Digital", "SSB": "Fonia (SSB)", "FM": "FM", "BCN": "Balizas", "ALL": "Todos os modos",
              "REP": "Repetidoras"}
MODE_LABELS = {"CW": "CW", "DIG": "Digitais", "SSB": "SSB", "AM": "AM", "FM": "FM", "DV": "Voz digital", "OUT": "Demais modos",
               "REP": "Repetidoras", "BCN": "Balizas"}

# Entidades DXCC (nomes do cty.dat) por região UIT, nos casos em que o continente do cty.dat não basta
_R1_ASIA = {"Asiatic Russia", "Kazakhstan", "Uzbekistan", "Turkmenistan", "Tajikistan", "Kyrgyzstan", "Mongolia", "Asiatic Turkey",
            "Armenia", "Azerbaijan", "Georgia", "Israel", "Jordan", "Lebanon", "Syria", "Iraq", "Saudi Arabia", "Kuwait", "Bahrain",
            "Qatar", "United Arab Emirates", "Oman", "Yemen", "Cyprus"}
_R2_OCEANIA = {"Hawaii", "Kure Island", "Midway Island", "Palmyra & Jarvis Islands", "Johnston Island"}


@dataclass
class Segment:
    band: str
    start: int
    stop: int
    use: str
    modes: list[str] = field(default_factory=list)  # modos liberados (vazio = plano genérico, sem detalhe)
    classes: str = ""                               # classes que podem usar, ex.: "AB" (vazio = não especificado)
    note: str = ""


@dataclass
class TxStatus:
    level: str   # ok, outside, class, mode, beacon, repeater
    text: str

    @property
    def ok(self) -> bool:
        return self.level == "ok"


def iaru_region(entity_name: str, continent: str) -> int:
    """Região UIT/IARU (1, 2 ou 3) de uma entidade DXCC."""
    if entity_name in _R1_ASIA:
        return 1
    if entity_name in _R2_OCEANIA:
        return 2
    return {"EU": 1, "AF": 1, "NA": 2, "SA": 2, "AS": 3, "OC": 3}.get(continent, 2)


def choose_plan(callsign: str, lat: float, lon: float, cty=None) -> str:
    """Escolhe o plano pelo indicativo (entidade DXCC) ou, sem indicativo, pela posição."""
    ent = cty.lookup(callsign) if (cty and callsign) else None
    if ent is None and (lat or lon) and -33.8 <= lat <= 5.3 and -73.9 <= lon <= -34.8:
        return "BR"  # caixa aproximada do Brasil; o indicativo é mais confiável, e há seleção manual
    if ent is None and cty is not None and (lat or lon):
        from . import geo

        entities = {e.name: e for e in cty.prefixes.values()}.values()  # centro de cada entidade, uma vez cada
        ent = min(entities, key=lambda e: geo.distance_bearing(lat, lon, e.lat, e.lon)[0])
    if ent is None:
        return "IARU-R2"
    if ent.name == "Brazil":
        return "BR"
    return f"IARU-R{iaru_region(ent.name, ent.continent)}"


class BandPlan:
    def __init__(self, plan_id: str = "BR", custom_path: Optional[Path] = None) -> None:
        raw = json.loads((DATA / "bandplans.json").read_text(encoding="utf-8"))["plans"]
        custom = custom_path if custom_path is not None else app_dir() / "bandplans_custom.json"
        if custom.exists():
            try:
                raw.update(json.loads(custom.read_text(encoding="utf-8")).get("plans", {}))
            except (OSError, ValueError):
                pass
        self.plans = raw
        self.digital = json.loads((DATA / "digital_modes.json").read_text(encoding="utf-8"))
        self.other = json.loads((DATA / "other_bands.json").read_text(encoding="utf-8"))
        self.select(plan_id)

    # ---- seleção do plano ----
    def available(self) -> list[tuple[str, str]]:
        return [(pid, p["name"]) for pid, p in self.plans.items()]

    def select(self, plan_id: str) -> None:
        if plan_id not in self.plans:
            plan_id = "IARU-R2"
        self.plan_id = plan_id
        spec = self.plans[plan_id]
        self.info = spec
        self.bands = spec["bands"]
        self.segments = [Segment(b["name"], s["start"], s["stop"], s["use"], list(s.get("modes", [])), s.get("classes", ""),
                                 s.get("note", "")) for b in self.bands for s in b["segments"]]

    @property
    def name(self) -> str:
        return self.info["name"]

    @property
    def generic(self) -> bool:
        return bool(self.info.get("generic"))

    def max_power(self, license_class: str) -> Optional[int]:
        return (self.info.get("max_power") or {}).get(license_class)

    # ---- consultas ----
    def band_names(self) -> list[str]:
        return [b["name"] for b in self.bands]

    def band_range(self, name: str) -> tuple[int, int]:
        b = next(b for b in self.bands if b["name"] == name)
        return b["start"], b["stop"]

    def band_for(self, hz: int) -> Optional[str]:
        return next((b["name"] for b in self.bands if b["start"] <= hz <= b["stop"]), None)

    def segment_for(self, hz: int) -> Optional[Segment]:
        return next((s for s in self.segments if s.start <= hz < s.stop), None)

    def segments_in(self, low: int, high: int) -> list[Segment]:
        return [s for s in self.segments if s.stop > low and s.start < high]

    def other_in(self, low: int, high: int) -> list[dict]:
        return [o for o in self.other if o["stop"] > low and o["start"] < high]

    def outside_amateur(self, hz: int) -> bool:
        return self.segment_for(hz) is None

    def suggest_mode(self, hz: int) -> tuple[str, bool]:
        """(modo, usa DATA) sugerido para a frequência."""
        seg = self.segment_for(hz)
        if seg and seg.use == "CW":
            return "CW", False
        if seg and seg.use == "DIG":
            return "USB", True
        if seg and seg.use == "FM":
            return "FM", False
        return ("LSB" if hz < 10_000_000 else "USB"), False

    def digital_for_band(self, band: Optional[str]) -> list[dict]:
        if band is None:
            return self.digital
        return [d for d in self.digital if self.band_for(d["freq"]) == band]

    def digital_at(self, hz: int, tol: int = 3000) -> Optional[dict]:
        return next((d for d in self.digital if abs(d["freq"] - hz) <= tol), None)

    # ---- privilégios e verificação de transmissão ----
    @staticmethod
    def category(mode: str, data: bool = False) -> str:
        """Categoria de emissão usada nos planos a partir do modo do rádio."""
        if mode in ("CW", "CW-R"):
            return "CW"
        if mode in ("RTTY", "RTTY-R") or data:
            return "DIG"
        return {"AM": "AM", "FM": "FM"}.get(mode, "SSB")

    def tx_status(self, hz: int, license_class: str = "", category: str = "") -> TxStatus:
        """Avalia se transmitir em `hz` é compatível com o plano, a classe e a emissão. É um aviso, não um bloqueio."""
        seg = self.segment_for(hz)
        if seg is None:
            return TxStatus("outside", f"{hz / 1e3:.1f} kHz está fora das faixas de radioamador do plano {self.name}.")
        if seg.use == "BCN":
            return TxStatus("beacon", f"{seg.band}: segmento exclusivo de balizas ({seg.start / 1e3:g}–{seg.stop / 1e3:g} kHz).")
        if seg.use == "REP":
            return TxStatus("repeater", f"{seg.band}: segmento exclusivo de repetidoras ({seg.start / 1e3:g}–{seg.stop / 1e3:g} kHz).")
        if license_class and seg.classes and license_class not in seg.classes:
            allowed = "/".join(seg.classes)
            return TxStatus("class", f"{seg.band} em {seg.start / 1e3:g}–{seg.stop / 1e3:g} kHz é liberada só para a classe {allowed}; "
                                     f"sua licença é classe {license_class}.")
        if category and seg.modes and category not in seg.modes:
            have = ", ".join(MODE_LABELS.get(m, m) for m in seg.modes)
            return TxStatus("mode", f"{MODE_LABELS.get(category, category)} não consta como liberado em {seg.start / 1e3:g}–"
                                    f"{seg.stop / 1e3:g} kHz (liberados: {have}).")
        return TxStatus("ok", "")
