"""Geometria do mapa: continentes, círculo máximo, posição do Sol e iluminação (dia/noite)."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

WORLD = Path(__file__).parent / "data" / "world.json"


def load_lines(kind: str = "borders") -> tuple[np.ndarray, np.ndarray]:
    """Polilinhas do mundo como (lon, lat) com NaN entre segmentos, prontas para um PlotCurveItem."""
    raw = json.loads(WORLD.read_text(encoding="utf-8"))[kind]
    xs: list[float] = []
    ys: list[float] = []
    for ring in raw:
        for x, y in ring:
            xs.append(x)
            ys.append(y)
        xs.append(float("nan"))
        ys.append(float("nan"))
    return np.array(xs), np.array(ys)


def great_circle(lat1: float, lon1: float, lat2: float, lon2: float, n: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Pontos do círculo máximo; insere NaN onde cruza o meridiano de ±180° para não riscar o mapa."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = 2 * math.asin(min(1.0, math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2)))
    if d < 1e-9:
        return np.array([lon1]), np.array([lat1])
    f = np.linspace(0, 1, n)
    a, b = np.sin((1 - f) * d) / math.sin(d), np.sin(f * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    lat = np.degrees(np.arctan2(z, np.hypot(x, y)))
    lon = np.degrees(np.arctan2(y, x))
    jumps = np.where(np.abs(np.diff(lon)) > 180)[0]
    for i in reversed(jumps):
        lon = np.insert(lon, i + 1, np.nan)
        lat = np.insert(lat, i + 1, np.nan)
    return lon, lat


def sun_position(when: datetime) -> tuple[float, float]:
    """(declinação, longitude subsolar) em graus — aproximação de baixa precisão (< 0,5°)."""
    when = when.astimezone(timezone.utc)
    jd = when.timestamp() / 86400.0 + 2440587.5
    n = jd - 2451545.0
    g = math.radians((357.529 + 0.98560028 * n) % 360)
    q = (280.459 + 0.98564736 * n) % 360
    lam = math.radians((q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    eps = math.radians(23.439 - 0.00000036 * n)
    dec = math.degrees(math.asin(math.sin(eps) * math.sin(lam)))
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam)))
    gmst = (280.46061837 + 360.98564736629 * n) % 360
    lon = (ra - gmst + 180) % 360 - 180
    return dec, lon


def sun_elevation(lat: float, lon: float, when: datetime) -> float:
    dec, slon = sun_position(when)
    p, d = math.radians(lat), math.radians(dec)
    h = math.radians(lon - slon)
    return math.degrees(math.asin(math.sin(p) * math.sin(d) + math.cos(p) * math.cos(d) * math.cos(h)))


def darkness_grid(when: datetime, step: int = 2) -> np.ndarray:
    """Matriz [lat de 90 a -90][lon de -180 a 180] com 0 (dia) a 1 (noite), com crepúsculo suave."""
    dec, slon = sun_position(when)
    lats = np.radians(np.arange(90, -90 - step, -step))[:, None]
    lons = np.radians(np.arange(-180, 180 + step, step) - slon)[None, :]
    d = math.radians(dec)
    elev = np.degrees(np.arcsin(np.sin(lats) * math.sin(d) + np.cos(lats) * math.cos(d) * np.cos(lons)))
    return np.clip((6 - elev) / 18, 0, 1)  # 0 acima de +6°, 1 abaixo de -12°
