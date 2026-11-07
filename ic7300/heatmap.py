"""Mapa de calor de propagação HF estimado para a frequência de operação.

É uma ESTIMATIVA simplificada, não substitui VOACAP/ITURHFProp:
- foF2 a partir do fluxo solar (SFI) e da altura do Sol no ponto médio do caminho;
- MUF = foF2 x fator de salto (geometria de uma camada a 300 km, saltos de até 4000 km);
- perda por absorção: fundo diurno simples + absorção da região D medida pelo NOAA (D-RAP), proporcional a 1/f²;
- queda da MUF com índice Kp alto.
Use junto com os relatos reais (PSK Reporter, WSPR), que mostram o que de fato chegou.
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from . import mapdata

R_EARTH = 6371.0
H_F2 = 300.0
HOP_MAX_KM = 4000.0
BASE_HAF_MHZ = 6.0   # absorção de fundo da região D com o Sol a pino (valor aproximado)


def ssn_from_sfi(sfi: float) -> float:
    """Número de manchas efetivo a partir do fluxo solar de 10,7 cm (relação aproximada)."""
    return max(0.0, (sfi - 63.7) / 0.728)


def fof2(sun_elev_deg: np.ndarray, sfi: float) -> np.ndarray:
    ssn = min(ssn_from_sfi(sfi), 200.0)
    day = 4.5 + 0.045 * ssn
    night = 0.45 * day
    w = np.clip((sun_elev_deg + 6.0) / 36.0, 0.0, 1.0) ** 0.6
    return night + (day - night) * w


def hop_factor(hop_km: np.ndarray) -> np.ndarray:
    """Fator M = 1/cos(i) de um salto de comprimento hop_km (ângulo de partida mínimo de 2°)."""
    alpha = np.maximum(hop_km, 1.0) / (2 * R_EARTH)
    ratio = R_EARTH / (R_EARTH + H_F2)
    beta = np.arctan2(np.cos(alpha) - ratio, np.sin(alpha))
    beta = np.maximum(beta, math.radians(2.0))
    sin_i = ratio * np.cos(beta)
    return 1.0 / np.sqrt(1.0 - np.clip(sin_i, 0, 0.999) ** 2)


def _sun_elev(lat_deg: np.ndarray, lon_deg: np.ndarray, when: datetime) -> np.ndarray:
    dec, slon = mapdata.sun_position(when)
    p, d = np.radians(lat_deg), math.radians(dec)
    h = np.radians(lon_deg - slon)
    return np.degrees(np.arcsin(np.sin(p) * math.sin(d) + np.cos(p) * math.cos(d) * np.cos(h)))


def estimate_grid(home: tuple[float, float], freq_hz: float, sfi: float, kp: float, when: datetime,
                  haf: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None, step: int = 3):
    """(lats, lons, Z) com Z de 0 a 1 = chance estimada de a frequência fechar entre o seu QTH e cada ponto do mapa.

    haf: opcional (lats, lons, matriz[lat][lon]) em MHz do D-RAP do NOAA.
    """
    f = max(freq_hz / 1e6, 1.0)
    lats = np.arange(-90, 91, step, dtype=float)
    lons = np.arange(-180, 181, step, dtype=float)
    la, lo = np.meshgrid(lats, lons, indexing="ij")
    p1, l1 = math.radians(home[0]), math.radians(home[1])
    p2, l2 = np.radians(la), np.radians(lo)
    dl = l2 - l1
    c = 2 * np.arcsin(np.sqrt(np.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2))
    dist = c * R_EARTH
    # ponto médio do caminho
    bx, by = np.cos(p2) * np.cos(dl), np.cos(p2) * np.sin(dl)
    pm = np.arctan2(math.sin(p1) + np.sin(p2), np.sqrt((math.cos(p1) + bx) ** 2 + by ** 2))
    lm = l1 + np.arctan2(by, math.cos(p1) + bx)
    mid_lat, mid_lon = np.degrees(pm), (np.degrees(lm) + 180) % 360 - 180

    hops = np.maximum(1, np.ceil(dist / HOP_MAX_KM))
    elev = _sun_elev(mid_lat, mid_lon, when)
    muf = fof2(elev, sfi) * hop_factor(dist / hops) * 0.9
    muf = muf * (1.0 - 0.05 * max(0.0, kp - 3.0))
    p_muf = 1.0 / (1.0 + np.exp(-(muf - f) / (0.08 * muf + 0.3)))

    day_w = np.clip((elev + 6.0) / 36.0, 0.0, 1.0)
    loss = hops * (BASE_HAF_MHZ / f) ** 2 * day_w
    if haf is not None:
        hl, ho, hz = haf
        i = np.abs(hl[:, None] - mid_lat.ravel()[None, :]).argmin(axis=0)
        j = np.abs(ho[:, None] - mid_lon.ravel()[None, :]).argmin(axis=0)
        loss = loss + hops * (hz[i, j].reshape(mid_lat.shape) / f) ** 2
    z = p_muf * np.exp(-loss / 8.0)
    z[dist < 50] = 1.0
    return lats, lons, z


def classify(p: float) -> str:
    return "boa" if p >= 0.66 else ("regular" if p >= 0.33 else ("fraca" if p >= 0.1 else "fechada"))


def sample(lats: np.ndarray, lons: np.ndarray, z: np.ndarray, lat: float, lon: float) -> float:
    i = int(np.abs(lats - lat).argmin())
    j = int(np.abs(lons - lon).argmin())
    return float(z[i, j])


def colorize(z: np.ndarray, kind: str = "prop") -> np.ndarray:
    """RGBA (uint8) para uma matriz [lat][lon]. 'prop' vai de vermelho (fechada) a verde (boa); 'seq' é uma escala azul-laranja."""
    z = np.clip(z, 0.0, 1.0)
    rgba = np.zeros(z.shape + (4,), dtype=np.uint8)
    if kind == "prop":
        rgba[..., 0] = (255 * np.clip(2 * (1 - z), 0, 1)).astype(np.uint8)
        rgba[..., 1] = (255 * np.clip(2 * z, 0, 1)).astype(np.uint8)
        rgba[..., 2] = 40
        rgba[..., 3] = (60 + 110 * z).astype(np.uint8)
    else:
        rgba[..., 0] = (40 + 215 * z).astype(np.uint8)
        rgba[..., 1] = (120 + 60 * (1 - abs(2 * z - 1))).astype(np.uint8)
        rgba[..., 2] = (255 * (1 - z)).astype(np.uint8)
        rgba[..., 3] = (35 + 150 * z).astype(np.uint8)
    return rgba
