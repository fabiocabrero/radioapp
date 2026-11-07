"""Satélites amadores: elementos orbitais (CelesTrak, grupo 'amateur'), posição, passagens e Doppler.

Propagação kepleriana com deriva secular por J2 (sem arrasto nem SGP4 completo), vetorizada com numpy: serve para ver onde
o satélite está e prever as passagens sobre o QTH com erro de ordem de minutos (cresce com a idade dos elementos). Para
operar com margem, confira com uma ferramenta dedicada (AMSAT, Gpredict).
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from .settings import app_dir

URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=json"
USER_AGENT = "IC7300App/0.1 (+https://github.com/fabiocabrero/radioapp)"
MU = 398600.4418        # km^3/s^2
RE = 6378.137           # km
J2 = 1.08263e-3
C_KMS = 299792.458
CACHE_MAX_AGE = 12 * 3600


@dataclass
class Sat:
    name: str
    norad: int
    epoch: datetime
    n_rev_day: float
    ecc: float
    inc: float
    raan: float
    argp: float
    ma: float

    @property
    def age_days(self) -> float:
        return (datetime.now(timezone.utc) - self.epoch).total_seconds() / 86400.0


@dataclass
class Pass:
    sat: Sat
    aos: datetime
    los: datetime
    tca: datetime
    max_el: float
    az_aos: float
    az_tca: float
    az_los: float

    @property
    def seconds(self) -> float:
        return (self.los - self.aos).total_seconds()


def parse_gp(rows: list) -> list[Sat]:
    out = []
    for r in rows:
        try:
            out.append(Sat(r["OBJECT_NAME"], int(r["NORAD_CAT_ID"]),
                           datetime.fromisoformat(r["EPOCH"]).replace(tzinfo=timezone.utc), float(r["MEAN_MOTION"]),
                           float(r["ECCENTRICITY"]), float(r["INCLINATION"]), float(r["RA_OF_ASC_NODE"]),
                           float(r["ARG_OF_PERICENTER"]), float(r["MEAN_ANOMALY"])))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def fetch_sats(timeout: float = 25, use_cache: bool = True) -> list[Sat]:
    """Elementos do CelesTrak, com cópia em disco por 12 h (o CelesTrak pede para não consultar com frequência)."""
    path = app_dir() / "celestrak_amateur.json"
    if use_cache and path.exists() and time.time() - path.stat().st_mtime < CACHE_MAX_AGE:
        try:
            return parse_gp(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    rows = json.loads(raw)
    try:
        path.write_bytes(raw)
    except OSError:
        pass
    return parse_gp(rows)


# ---------------------------------------------------------------------------------------------- geometria
def _gmst(unix: np.ndarray) -> np.ndarray:
    jd = unix / 86400.0 + 2440587.5
    t = (jd - 2451545.0) / 36525.0
    g = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * t * t
    return np.radians(g % 360.0)


def _kepler(m: np.ndarray, e: float) -> np.ndarray:
    ea = m.copy()
    for _ in range(10):
        ea = ea - (ea - e * np.sin(ea) - m) / (1 - e * np.cos(ea))
    return ea


def eci_arr(sat: Sat, unix: np.ndarray) -> np.ndarray:
    """Posições ECI (3 x N, km) nos instantes `unix` (segundos desde 1970)."""
    n = sat.n_rev_day * 2 * math.pi / 86400.0
    a = (MU / n ** 2) ** (1 / 3)
    dt = unix - sat.epoch.timestamp()
    i, e = math.radians(sat.inc), sat.ecc
    p = a * (1 - e * e)
    k = 1.5 * J2 * (RE / p) ** 2 * n
    raan = math.radians(sat.raan) - k * math.cos(i) * dt
    argp = math.radians(sat.argp) + 0.5 * k * (5 * math.cos(i) ** 2 - 1) * dt
    ea = _kepler((math.radians(sat.ma) + n * dt) % (2 * math.pi), e)
    nu = 2 * np.arctan2(math.sqrt(1 + e) * np.sin(ea / 2), math.sqrt(1 - e) * np.cos(ea / 2))
    r = a * (1 - e * np.cos(ea))
    x, y = r * np.cos(nu), r * np.sin(nu)
    cw, sw, co, so = np.cos(argp), np.sin(argp), np.cos(raan), np.sin(raan)
    ci, si = math.cos(i), math.sin(i)
    return np.array([x * (co * cw - so * sw * ci) - y * (co * sw + so * cw * ci),
                     x * (so * cw + co * sw * ci) - y * (so * sw - co * cw * ci),
                     x * sw * si + y * cw * si])


def eci(sat: Sat, when: datetime) -> np.ndarray:
    return eci_arr(sat, np.array([when.timestamp()]))[:, 0]


def subpoint(sat: Sat, when: datetime) -> tuple[float, float, float]:
    """(lat, lon, altitude em km) abaixo do satélite."""
    x, y, z = eci(sat, when)
    th = float(_gmst(np.array([when.timestamp()]))[0])
    lon = (math.degrees(math.atan2(y, x) - th) + 180) % 360 - 180
    rxy = math.hypot(x, y)
    lat = math.atan2(z, rxy)
    e2 = 0.00669438
    for _ in range(5):  # latitude geodésica
        s = math.sin(lat)
        nn = RE / math.sqrt(1 - e2 * s * s)
        lat = math.atan2(z + e2 * nn * s, rxy)
    s = math.sin(lat)
    nn = RE / math.sqrt(1 - e2 * s * s)
    alt = rxy / math.cos(lat) - nn if abs(math.cos(lat)) > 1e-6 else abs(z) - nn
    return math.degrees(lat), lon, alt


def _topo(sat: Sat, unix: np.ndarray, lat: float, lon: float):
    """(elevação°, azimute°, distância km) do satélite visto do ponto, para cada instante."""
    s = eci_arr(sat, unix)
    th = _gmst(unix) + math.radians(lon)
    p = math.radians(lat)
    up = np.array([math.cos(p) * np.cos(th), math.cos(p) * np.sin(th), np.full_like(th, math.sin(p))])
    east = np.array([-np.sin(th), np.cos(th), np.zeros_like(th)])
    north = np.cross(up, east, axis=0)
    rho = s - RE * up
    rng = np.linalg.norm(rho, axis=0)
    el = np.degrees(np.arcsin(np.clip((rho * up).sum(axis=0) / rng, -1, 1)))
    az = np.degrees(np.arctan2((rho * east).sum(axis=0), (rho * north).sum(axis=0))) % 360
    return el, az, rng


def look_angles(sat: Sat, when: datetime, lat: float, lon: float) -> tuple[float, float]:
    el, az, _ = _topo(sat, np.array([when.timestamp()]), lat, lon)
    return float(el[0]), float(az[0])


def range_rate(sat: Sat, when: datetime, lat: float, lon: float) -> float:
    """Velocidade radial em km/s (positiva = afastando)."""
    t = when.timestamp()
    _, _, r = _topo(sat, np.array([t - 0.5, t + 0.5]), lat, lon)
    return float(r[1] - r[0])


def doppler(freq_hz: float, rr_kms: float) -> float:
    """Frequência recebida em Hz de um sinal de freq_hz emitido pelo satélite."""
    return freq_hz * (1 - rr_kms / C_KMS)


def track(sat: Sat, start: datetime, end: datetime, lat: float, lon: float, step: float = 10.0):
    """(instantes datetime, elevação, azimute, distância) de start a end."""
    t0 = start.timestamp()
    unix = np.arange(t0, end.timestamp() + step, step)
    el, az, rng = _topo(sat, unix, lat, lon)
    return [datetime.fromtimestamp(u, timezone.utc) for u in unix], el, az, rng


def next_passes(sat: Sat, lat: float, lon: float, start: Optional[datetime] = None, hours: float = 24.0,
                min_el: float = 10.0, step: float = 15.0) -> list[Pass]:
    start = start or datetime.now(timezone.utc)
    t0 = start.timestamp()
    unix = np.arange(t0, t0 + hours * 3600, step)
    el, az, _ = _topo(sat, unix, lat, lon)
    above = el >= 0.0
    out: list[Pass] = []
    idx = np.flatnonzero(np.diff(above.astype(np.int8)))  # bordas de subida e descida
    edges = list(idx + 1)
    if above[0]:
        edges.insert(0, 0)
    if above[-1]:
        edges.append(len(above))
    for k in range(0, len(edges) - 1, 2):
        a, b = edges[k], edges[k + 1]
        seg = slice(a, b)
        if b - a < 2:
            continue
        imax = a + int(np.argmax(el[seg]))
        if el[imax] < min_el:
            continue
        out.append(Pass(sat, datetime.fromtimestamp(unix[a], timezone.utc), datetime.fromtimestamp(unix[b - 1], timezone.utc),
                        datetime.fromtimestamp(unix[imax], timezone.utc), float(el[imax]), float(az[a]), float(az[imax]),
                        float(az[b - 1])))
    return out
