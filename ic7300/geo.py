"""Localização: grid Maidenhead, distância e azimute, GPS por NMEA."""
from __future__ import annotations

import math
import re
import threading
from typing import Callable, Optional

_GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2}([0-9]{2})?)?$", re.I)


def valid_grid(grid: str) -> bool:
    return len(grid) in (4, 6, 8) and bool(_GRID_RE.match(grid))


def latlon_to_grid(lat: float, lon: float, precision: int = 6) -> str:
    lon += 180.0
    lat += 90.0
    out = chr(ord("A") + int(lon // 20)) + chr(ord("A") + int(lat // 10))
    lon %= 20
    lat %= 10
    out += str(int(lon // 2)) + str(int(lat // 1))
    lon = (lon % 2) * 12
    lat = (lat % 1) * 24
    out += chr(ord("a") + int(lon)) + chr(ord("a") + int(lat))
    if precision >= 8:
        lon = (lon % 1) * 10
        lat = (lat % 1) * 10
        out += str(int(lon)) + str(int(lat))
    return out[:precision]


def grid_to_latlon(grid: str) -> tuple[float, float]:
    """Centro do quadrado."""
    if not valid_grid(grid):
        raise ValueError(f"Grid inválido: {grid!r}")
    g = grid.upper()
    lon = (ord(g[0]) - 65) * 20 - 180
    lat = (ord(g[1]) - 65) * 10 - 90
    lon += int(g[2]) * 2
    lat += int(g[3])
    size_lon, size_lat = 2.0, 1.0
    if len(g) >= 6:
        size_lon, size_lat = 2 / 24, 1 / 24
        lon += (ord(g[4]) - 65) * size_lon
        lat += (ord(g[5]) - 65) * size_lat
    if len(g) == 8:
        size_lon, size_lat = size_lon / 10, size_lat / 10
        lon += int(g[6]) * size_lon
        lat += int(g[7]) * size_lat
    return lat + size_lat / 2, lon + size_lon / 2


def distance_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """(distância em km, azimute inicial em graus)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    dist = 2 * r * math.asin(min(1.0, math.sqrt(a)))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return dist, (math.degrees(math.atan2(y, x)) + 360) % 360


def _nmea_deg(value: str, hemi: str) -> float:
    dot = value.index(".")
    deg = float(value[: dot - 2]) + float(value[dot - 2:]) / 60
    return -deg if hemi in "SW" else deg


def parse_nmea(line: str) -> Optional[tuple[float, float]]:
    """Extrai (lat, lon) de sentenças GGA/RMC válidas."""
    line = line.strip()
    if not line.startswith("$") or "*" not in line:
        return None
    body, _, checksum = line[1:].partition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        if calc != int(checksum[:2], 16):
            return None
    except ValueError:
        return None
    f = body.split(",")
    kind = f[0][-3:]
    try:
        if kind == "GGA" and f[6] not in ("", "0"):
            return _nmea_deg(f[2], f[3]), _nmea_deg(f[4], f[5])
        if kind == "RMC" and f[2] == "A":
            return _nmea_deg(f[3], f[4]), _nmea_deg(f[5], f[6])
    except (ValueError, IndexError):
        return None
    return None


class GpsReader:
    """Lê um receptor GPS NMEA em porta serial e informa a posição."""

    def __init__(self, port: str, baud: int, on_fix: Callable[[float, float], None]) -> None:
        self.port, self.baud, self.on_fix = port, baud, on_fix
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import serial

        with serial.Serial(self.port, self.baud, timeout=1) as ser:
            while not self._stop.is_set():
                raw = ser.readline().decode("ascii", "ignore")
                fix = parse_nmea(raw)
                if fix:
                    self.on_fix(*fix)
