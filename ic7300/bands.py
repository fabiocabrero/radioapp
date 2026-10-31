"""Plano de bandas, frequências de modos digitais e sugestão de modo."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DATA = Path(__file__).parent / "data"

# Cor de cada uso no plano de bandas (RGB)
USE_COLORS = {"CW": (230, 160, 40), "DIG": (60, 170, 230), "SSB": (90, 200, 120), "FM": (200, 100, 200),
              "BCN": (230, 80, 80), "ALL": (150, 150, 150)}
USE_LABELS = {"CW": "CW", "DIG": "Digital", "SSB": "Fonia (SSB)", "FM": "FM", "BCN": "Balizas", "ALL": "Todos os modos"}


@dataclass
class Segment:
    band: str
    start: int
    stop: int
    use: str


class BandPlan:
    def __init__(self, path: Path = DATA / "bands.json") -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.bands = raw["bands"]
        self.segments = [Segment(b["name"], s["start"], s["stop"], s["use"]) for b in self.bands for s in b["segments"]]
        self.digital = json.loads((DATA / "digital_modes.json").read_text(encoding="utf-8"))
        self.other = json.loads((DATA / "other_bands.json").read_text(encoding="utf-8"))

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
