"""Ondas curtas: grade de emissoras do EiBi (Eike Bierwirth, www.eibispace.de) filtrada por horário e local."""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import geo

EIBI_URL = "http://www.eibispace.de/dx/sked-{}.csv"
HEADER = "kHz:75;Time(UTC):93;Days:59;ITU:49;Station:201;Lng:49;Target:62;Remarks:135;P:35;Start:60;Stop:60;"
MIN_STATIONS = 1000
_STATION = re.compile(r"\d+(\.\d+)?;\d{4}-\d{4};")
_WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# País (código ITU) -> (lat, lon) aproximados do centro; só serve para distância e alvo
COUNTRY_POS = {
    "CHN": (35, 103), "TWN": (23.7, 121), "USA": (39, -98), "RUS": (60, 60), "G": (54, -2), "J": (36, 138),
    "CAN": (56, -96), "VTN": (16, 106), "KRE": (40, 127), "E": (40, -4), "POL": (52, 19), "AUS": (-25, 134),
    "F": (46.5, 2.5), "ROU": (46, 25), "NOR": (62, 10), "CVA": (41.9, 12.45), "IRN": (32, 53), "NZL": (-41, 174),
    "IND": (22, 79), "SWZ": (-26.5, 31.5), "KOR": (36.5, 128), "IRL": (53, -8), "TUR": (39, 35), "D": (51, 10),
    "CUB": (22, -79), "PHL": (12.5, 122), "ALG": (28, 3), "ISL": (65, -18), "B": (-10, -52), "THA": (15, 101),
    "ALS": (64, -150), "GRC": (39, 22), "HOL": (52, 5), "HNG": (47, 19), "INS": (-2, 118), "I": (42.5, 12.5),
    "EQA": (-1.5, -78), "HWA": (20, -157), "S": (62, 15), "DNK": (56, 10), "FIN": (64, 26), "CHL": (-33, -71),
    "CZE": (49.8, 15.5), "CNR": (28.3, -16), "GUM": (13.4, 144.8), "VUT": (-16, 167), "SVK": (48.7, 19.5),
    "MYA": (21, 96), "MDG": (-19, 47), "MLA": (4, 102), "HKG": (22.3, 114.2), "AZR": (38.7, -27.2),
    "PRU": (-10, -75), "KGZ": (41, 74.5), "BOL": (-17, -65), "PTR": (18.2, -66.5), "ETH": (9, 40),
    "BEL": (50.5, 4.5), "AFS": (-29, 24), "MNG": (47, 105), "TUN": (34, 9), "ARG": (-34, -64), "EGY": (27, 30),
    "BHR": (26, 50.5), "ISR": (31.5, 35), "UKR": (49, 32), "BER": (32.3, -64.8), "PNR": (-23, -58),
    "BLR": (53.7, 28), "CLM": (4, -72), "TRD": (10.5, -61.3), "MLI": (17, -4), "UZB": (41, 64),
    "SLM": (-9, 160), "CLN": (7.9, 80.7), "MEX": (23, -102), "FJI": (-17.7, 178), "OCE": (-17.7, -149.4),
    "BUL": (42.7, 25.5), "SOM": (5, 46), "SEN": (14.5, -14.5), "TCD": (15, 19), "MRT": (20, -10.5),
    "LBR": (6.4, -9.4), "COG": (-1, 15), "SUI": (46.8, 8.2), "SNG": (1.35, 103.8), "KWT": (29.3, 47.5),
    "KEN": (0.5, 38), "CTI": (7.5, -5.5), "PAK": (30, 70), "CYM": (19.3, -81.2), "NCG": (13, -85),
    "SEY": (-4.7, 55.5), "AFG": (33, 65), "NPL": (28, 84), "NIG": (9, 8), "COD": (-2, 23), "BGD": (24, 90),
    "MOZ": (-18, 35), "SSD": (7, 30), "AGL": (-12, 18), "SDN": (15, 30), "VEN": (7, -66), "BTN": (27.5, 90.4),
}
_COUNTRY_RADIUS = {"RUS": 40, "CAN": 25, "USA": 22, "CHN": 20, "AUS": 22, "B": 20, "IND": 14, "ARG": 15, "ALS": 10}

# Regiões-alvo: (lat_min, lat_max, lon_min, lon_max); lon_min > lon_max atravessa o antimeridiano
REGIONS = {
    "Eu": (35, 72, -25, 45), "WEu": (36, 60, -12, 15), "NEu": (55, 72, -10, 40), "EEu": (44, 60, 20, 45),
    "CEu": (44, 56, 5, 25), "SEu": (35, 46, -10, 28), "SEE": (35, 48, 13, 30),
    "NAm": (25, 72, -170, -52), "ENA": (25, 50, -95, -52), "WNA": (25, 55, -130, -95), "CAm": (7, 22, -93, -77),
    "Car": (10, 27, -86, -59), "SAm": (-56, 13, -82, -34), "LAm": (-56, 32, -118, -34), "Am": (-56, 72, -170, -34),
    "Af": (-35, 37, -18, 52), "NAf": (15, 37, -18, 35), "WAf": (4, 20, -18, 15), "CAf": (-12, 12, 8, 32),
    "EAf": (-12, 18, 28, 52), "SAf": (-35, -12, 10, 41),
    "ME": (12, 42, 25, 63), "SAs": (5, 36, 60, 95), "CAs": (35, 55, 50, 90), "SEA": (-11, 28, 92, 141),
    "FE": (18, 55, 95, 150), "As": (0, 55, 35, 150), "NAs": (50, 75, 60, 180), "Sib": (50, 75, 60, 180),
    "Cau": (38, 46, 36, 50), "CIS": (36, 72, 26, 180), "Oc": (-50, 10, 110, -120), "WOc": (-50, 0, 110, 160),
    "EOc": (-30, 10, 160, -120), "NOc": (0, 25, 130, -150), "SOc": (-50, -20, 110, -120),
    "NAO": (25, 65, -60, -5), "NIn": (20, 36, 68, 90), "SIn": (5, 20, 70, 90),
    "Glo": (-90, 90, -180, 180), "Wor": (-90, 90, -180, 180),
}


def target_covers(target: str, lat: float, lon: float) -> Optional[bool]:
    """True/False se o alvo cobre o ponto; None se o código do alvo é desconhecido."""
    if not target:
        return None
    for code in re.split(r"[,/]", target):
        code = code.strip()
        if code in REGIONS:
            la0, la1, lo0, lo1 = REGIONS[code]
            in_lon = lo0 <= lon <= lo1 if lo0 <= lo1 else (lon >= lo0 or lon <= lo1)
            if la0 <= lat <= la1 and in_lon:
                return True
        elif code in COUNTRY_POS:
            clat, clon = COUNTRY_POS[code]
            if geo.distance_bearing(clat, clon, lat, lon)[0] / 111.0 <= _COUNTRY_RADIUS.get(code, 12):
                return True
        else:
            return None
    return False


@dataclass
class Entry:
    freq_khz: float
    start_min: int
    end_min: int
    days: str
    itu: str
    station: str
    lang: str
    target: str
    remarks: str
    power: float
    date_start: str
    date_stop: str

    @property
    def freq_hz(self) -> int:
        return int(round(self.freq_khz * 1000))

    def position(self) -> Optional[tuple[float, float]]:
        return COUNTRY_POS.get(self.itu)


def parse_schedule(text: str) -> list[Entry]:
    entries = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not _STATION.match(line):
            continue
        f = line.split(";")
        if len(f) < 9:
            continue
        f += [""] * (11 - len(f))
        t = f[1]
        try:
            entries.append(Entry(float(f[0]), int(t[:2]) * 60 + int(t[2:4]), int(t[5:7]) * 60 + int(t[7:9]), f[2], f[3],
                                 f[4], f[5], f[6], f[7], float(f[8] or 0), f[9], f[10]))
        except ValueError:
            continue
    return entries


def _day_set(days: str, today: date) -> Optional[set[int]]:
    """Conjunto de dias da semana (0 = segunda) ou None se a regra for desconhecida (irr, alt, Test...)."""
    days = days.strip()
    if not days:
        return set(range(7))
    m = re.fullmatch(r"(\d{1,2})([A-Za-z]{3})", days)
    if m:
        return set(range(7)) if today.day == int(m.group(1)) and _MONTHS[today.month - 1] == m.group(2) else set()
    if re.fullmatch(r"[1-7]+", days):
        return {int(c) - 1 for c in days}
    if re.fullmatch(r"\d\.(Mo|Tu|We|Th|Fr|Sa|Su)", days):
        nth, wd = int(days[0]), _WEEKDAYS.index(days[2:])
        return {wd} if (today.day - 1) // 7 + 1 == nth else set()
    result: set[int] = set()
    for part in days.split(","):
        part = part.strip()
        rng = re.fullmatch(r"(Mo|Tu|We|Th|Fr|Sa|Su)-(Mo|Tu|We|Th|Fr|Sa|Su)", part)
        if rng:
            a, b = _WEEKDAYS.index(rng.group(1)), _WEEKDAYS.index(rng.group(2))
            result |= {(a + i) % 7 for i in range(((b - a) % 7) + 1)}
            continue
        names = re.findall(r"Mo|Tu|We|Th|Fr|Sa|Su", part)
        if names and "".join(names) == part:
            result |= {_WEEKDAYS.index(n) for n in names}
            continue
        return None
    return result


def _in_date_range(start: str, stop: str, today: date) -> bool:
    """Start/Stop em ddmm (ex.: 0110 = 1 de outubro); intervalos que viram o ano são aceitos."""
    if not (re.fullmatch(r"\d{4}", start) and re.fullmatch(r"\d{4}", stop)):
        return True
    s = (int(start[2:]), int(start[:2]))
    e = (int(stop[2:]), int(stop[:2]))
    now = (today.month, today.day)
    return s <= now <= e if s <= e else (now >= s or now <= e)


def on_air(entry: Entry, utc: datetime) -> Optional[bool]:
    """True/False se a emissora está no ar em `utc`; None se a regra de dias é irregular (talvez)."""
    minute = utc.hour * 60 + utc.minute
    s, e = entry.start_min, entry.end_min
    if s == e:
        in_window, after_midnight = False, False
    elif s < e:
        in_window, after_midnight = s <= minute < e, False
    else:
        in_window, after_midnight = minute >= s or minute < e, minute < e
    if not in_window:
        return False
    day = utc.date() - timedelta(days=1) if after_midnight else utc.date()
    if not _in_date_range(entry.date_start, entry.date_stop, day):
        return False
    days = _day_set(entry.days, day)
    if days is None:
        return None
    return day.weekday() in days


def minutes_left(entry: Entry, utc: datetime) -> int:
    minute = utc.hour * 60 + utc.minute
    return (entry.end_min - minute) % 1440 or 1440


def local_window(entry: Entry, utc: datetime) -> str:
    """Janela de transmissão no fuso horário do PC, como 'HH:MM–HH:MM'."""
    if entry.end_min - entry.start_min == 1440:
        return "24 h"
    base = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    start = (base + timedelta(minutes=entry.start_min)).astimezone()
    end = (base + timedelta(minutes=entry.end_min)).astimezone()
    return f"{start:%H:%M}–{end:%H:%M}"


def utc_window(entry: Entry) -> str:
    end = entry.end_min if entry.end_min != 1440 else 1440
    return f"{entry.start_min // 60:02d}{entry.start_min % 60:02d}–{end // 60:02d}{end % 60:02d}"


def band_group(freq_khz: float) -> str:
    """Grupo do HamQSL mais próximo, só como indicativo da condição de propagação para a faixa."""
    if freq_khz < 7500:
        return "80m-40m"
    if freq_khz < 15000:
        return "30m-20m"
    if freq_khz < 22000:
        return "17m-15m"
    return "12m-10m"


def seasons(today: date) -> tuple[str, str]:
    """(temporada atual, anterior) como o EiBi nomeia: A = último domingo de março a último de outubro."""
    def last_sunday(year: int, month: int) -> date:
        d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    y = today.year
    if today < last_sunday(y, 3):
        return f"b{(y - 1) % 100:02d}", f"a{(y - 1) % 100:02d}"
    if today < last_sunday(y, 10):
        return f"a{y % 100:02d}", f"b{(y - 1) % 100:02d}"
    return f"b{y % 100:02d}", f"a{y % 100:02d}"


def validate(text: str) -> int:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != HEADER:
        raise ValueError("Arquivo não é a grade do EiBi")
    n = sum(1 for l in lines[1:] if _STATION.match(l))
    if n < MIN_STATIONS:
        raise ValueError("Grade do EiBi incompleta")
    return n


def download(today: Optional[date] = None, timeout: float = 60) -> tuple[str, str]:
    """Baixa a temporada vigente (ou a anterior, se ainda não publicada). Retorna (texto, temporada)."""
    last_error: Exception = ValueError("sem temporada")
    for season in seasons(today or date.today()):
        req = urllib.request.Request(EIBI_URL.format(season), headers={"User-Agent": "IC7300App/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                continue
            raise
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        validate(text)
        return text, season
    raise last_error


def load_file(path: Path) -> list[Entry]:
    return parse_schedule(path.read_text(encoding="utf-8", errors="replace"))
