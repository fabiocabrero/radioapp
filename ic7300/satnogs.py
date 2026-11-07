"""Transmissores de satélites amadores (SatNOGS DB): frequências de subida e descida, modo e situação.

Dados abertos do SatNOGS DB (https://db.satnogs.org); dê o crédito da fonte onde mostrar. A API é pública e de leitura.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .settings import app_dir

URL = "https://db.satnogs.org/api/transmitters/?format=json&alive=true&status=active&service=Amateur"
USER_AGENT = "IC7300App/0.1 (+https://github.com/fabiocabrero/radioapp)"
CACHE_MAX_AGE = 3 * 86400
IC7300_RANGE = (30_000, 74_800_000)   # alcance de recepção do IC-7300 usado pelo app (HF + 50 MHz; 70 MHz conforme versão)


@dataclass
class Transmitter:
    norad: int
    description: str
    kind: str                 # Transmitter | Transceiver | Transponder
    mode: str
    uplink_low: Optional[int]
    uplink_high: Optional[int]
    downlink_low: Optional[int]
    downlink_high: Optional[int]
    invert: bool = False
    baud: Optional[float] = None

    @property
    def down_center(self) -> Optional[int]:
        if self.downlink_low is None:
            return None
        return (self.downlink_low + (self.downlink_high or self.downlink_low)) // 2

    @property
    def up_center(self) -> Optional[int]:
        if self.uplink_low is None:
            return None
        return (self.uplink_low + (self.uplink_high or self.uplink_low)) // 2

    @property
    def rx_in_range(self) -> bool:
        """O IC-7300 consegue ouvir o downlink?"""
        c = self.down_center
        return c is not None and IC7300_RANGE[0] <= c <= IC7300_RANGE[1]

    @property
    def voice_or_linear(self) -> bool:
        return self.kind == "Transponder" or self.mode.upper() in ("FM", "USB", "LSB", "CW", "SSTV")

    def label(self) -> str:
        parts = [self.description or self.kind]
        if self.up_center:
            parts.append(f"↑ {self.up_center / 1e6:.4f}")
        if self.down_center:
            parts.append(f"↓ {self.down_center / 1e6:.4f}")
        parts.append(self.mode + (" inv." if self.invert else ""))
        return "  ".join(parts)


def parse_transmitters(rows: list) -> list[Transmitter]:
    out = []
    for r in rows:
        try:
            out.append(Transmitter(int(r["norad_cat_id"]), r.get("description") or "", r.get("type") or "", r.get("mode") or "",
                                   r.get("uplink_low"), r.get("uplink_high"), r.get("downlink_low"), r.get("downlink_high"),
                                   bool(r.get("invert")), r.get("baud")))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def by_norad(items: list[Transmitter]) -> dict[int, list[Transmitter]]:
    d: dict[int, list[Transmitter]] = {}
    for t in items:
        d.setdefault(t.norad, []).append(t)
    return d


def fetch_transmitters(timeout: float = 40, use_cache: bool = True) -> list[Transmitter]:
    path = app_dir() / "satnogs_transmitters.json"
    if use_cache and path.exists() and time.time() - path.stat().st_mtime < CACHE_MAX_AGE:
        try:
            return parse_transmitters(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    rows = json.loads(raw)
    try:
        path.write_bytes(raw)
    except OSError:
        pass
    return parse_transmitters(rows)


def radio_mode(mode: str) -> tuple[str, bool]:
    """(modo do IC-7300, DATA) para sintonizar um downlink."""
    m = mode.upper()
    if m == "FM":
        return "FM", False
    if m in ("LSB", "USB", "CW", "AM"):
        return m, False
    if m == "SSTV":
        return "USB", True
    return "USB", True   # telemetria e digitais: USB com DATA
