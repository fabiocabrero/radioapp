"""Propagação em tempo real: índices solares (HamQSL/N0NBH) e relatos de recepção (PSK Reporter)."""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import geo, mapdata

SOLAR_URL = "https://www.hamqsl.com/solarxml.php"
PSK_URL = "https://retrieve.pskreporter.info/query"
USER_AGENT = "IC7300App/0.1"

# Grupos do HamQSL e as bandas do app que cada grupo cobre
BAND_GROUPS = {"80m-40m": ["80m", "60m", "40m"], "30m-20m": ["30m", "20m"],
               "17m-15m": ["17m", "15m"], "12m-10m": ["12m", "10m"]}
CONDITION_PT = {"Good": "Boa", "Fair": "Regular", "Poor": "Fraca"}


@dataclass
class SolarData:
    updated: str = ""
    sfi: int = 0
    a_index: int = 0
    k_index: int = 0
    sunspots: int = 0
    xray: str = ""
    solar_wind: float = 0.0
    geomag: str = ""
    bands: dict = field(default_factory=dict)  # {("80m-40m", "day"): "Good", ...}

    def condition_for_group(self, group: str, daytime: bool) -> str:
        return self.bands.get((group, "day" if daytime else "night"), "")

    def condition_for(self, band: str, daytime: bool) -> str:
        for group, members in BAND_GROUPS.items():
            if band in members:
                return self.bands.get((group, "day" if daytime else "night"), "")
        return ""


def _int(text: str | None) -> int:
    try:
        return int(float((text or "").strip()))
    except ValueError:
        return 0


def parse_solar(xml_text: str) -> SolarData:
    root = ET.fromstring(xml_text).find("solardata")
    if root is None:
        raise ValueError("Resposta sem <solardata>")
    t = lambda tag: (root.findtext(tag) or "").strip()  # noqa: E731
    data = SolarData(updated=t("updated"), sfi=_int(t("solarflux")), a_index=_int(t("aindex")),
                     k_index=_int(t("kindex")), sunspots=_int(t("sunspots")), xray=t("xray"),
                     geomag=t("geomagfield"))
    try:
        data.solar_wind = float(t("solarwind"))
    except ValueError:
        pass
    for band in root.findall("calculatedconditions/band"):
        data.bands[(band.get("name", ""), band.get("time", ""))] = (band.text or "").strip()
    return data


def fetch_solar(timeout: float = 15) -> SolarData:
    req = urllib.request.Request(SOLAR_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_solar(resp.read().decode("utf-8", "replace"))


def is_daytime(lat: float, lon: float, when: datetime | None = None) -> bool:
    return mapdata.sun_elevation(lat, lon, when or datetime.now(timezone.utc)) > 0


@dataclass
class Report:
    sender: str
    sender_grid: str
    receiver: str
    receiver_grid: str
    freq: int
    mode: str
    snr: int
    when: int  # época UTC

    def mine_is_sender(self, call: str) -> bool:
        return self.sender.upper() == call.upper()


def parse_psk(xml_text: str) -> list[Report]:
    out = []
    for r in ET.fromstring(xml_text).iter("receptionReport"):
        try:
            out.append(Report(r.get("senderCallsign", ""), r.get("senderLocator", ""), r.get("receiverCallsign", ""),
                              r.get("receiverLocator", ""), int(r.get("frequency", "0")), r.get("mode", ""),
                              int(r.get("sNR", "0")), int(r.get("flowStartSeconds", "0"))))
        except ValueError:
            continue
    return out


def fetch_psk(callsign: str, heard_me: bool = True, seconds: int = 1800, timeout: float = 25) -> list[Report]:
    """Relatos recentes: quem me ouviu (heard_me) ou quem eu ouvi. O PSK Reporter pede no máximo 1 consulta a cada 5 min."""
    key = "senderCallsign" if heard_me else "receiverCallsign"
    url = f"{PSK_URL}?{key}={callsign.upper()}&flowStartSeconds=-{seconds}&rronly=1&appcontact=ic7300app"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_psk(resp.read().decode("utf-8", "replace"))


def report_endpoint(rep: Report, my_call: str) -> tuple[float, float] | None:
    """Posição da outra estação do relato (lat, lon) a partir do grid."""
    grid = rep.receiver_grid if rep.mine_is_sender(my_call) else rep.sender_grid
    try:
        return geo.grid_to_latlon(grid[:6] if len(grid) >= 6 else grid[:4])
    except ValueError:
        return None
