"""Tempo no local do contato e grade global de tempo (Open-Meteo, sem chave; uso não comercial)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "IC7300App/0.1 (+https://github.com/fabiocabrero/radioapp)"
VARS = "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,precipitation,weather_code,pressure_msl"

# códigos WMO usados pelo Open-Meteo
CODES = {0: "céu limpo", 1: "quase limpo", 2: "parcialmente nublado", 3: "nublado", 45: "neblina", 48: "neblina com geada",
         51: "garoa fraca", 53: "garoa", 55: "garoa forte", 61: "chuva fraca", 63: "chuva", 65: "chuva forte",
         66: "chuva congelante", 67: "chuva congelante forte", 71: "neve fraca", 73: "neve", 75: "neve forte",
         77: "grãos de neve", 80: "pancadas fracas", 81: "pancadas de chuva", 82: "pancadas fortes",
         85: "pancadas de neve", 86: "pancadas de neve fortes", 95: "trovoada", 96: "trovoada com granizo",
         99: "trovoada com granizo forte"}


@dataclass
class Weather:
    temp: float
    humidity: int
    clouds: int
    wind_kmh: float
    rain_mm: float
    pressure: float
    code: int

    @property
    def text(self) -> str:
        return CODES.get(self.code, f"código {self.code}")

    @property
    def stormy(self) -> bool:
        return self.code >= 95

    def summary(self) -> str:
        s = (f"{self.text}, {self.temp:.0f} °C, umidade {self.humidity}%, nuvens {self.clouds}%, vento {self.wind_kmh:.0f} km/h, "
             f"chuva {self.rain_mm:.1f} mm, {self.pressure:.0f} hPa")
        return s + " · ruído de tempestade provável em HF" if self.stormy else s


def parse_weather(payload: dict) -> Weather:
    c = payload["current"]
    return Weather(float(c["temperature_2m"]), int(c["relative_humidity_2m"]), int(c["cloud_cover"]),
                   float(c["wind_speed_10m"]), float(c["precipitation"]), float(c["pressure_msl"]), int(c["weather_code"]))


def _get(params: dict, timeout: float = 25):
    req = urllib.request.Request(f"{URL}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def fetch_weather(lat: float, lon: float) -> Weather:
    return parse_weather(_get({"latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}", "current": VARS}))


def fetch_grid(var: str = "cloud_cover", step: int = 15):
    """Grade global de uma variável atual (nuvens, precipitação...) a cada `step` graus. Várias coordenadas por chamada."""
    import numpy as np

    lats = list(range(-75, 76, step))
    lons = list(range(-180, 180, step))
    pts = [(la, lo) for la in lats for lo in lons]
    out = np.zeros((len(lats), len(lons)), dtype=np.float32)
    chunk = 100
    for i in range(0, len(pts), chunk):
        part = pts[i:i + chunk]
        data = _get({"latitude": ",".join(str(p[0]) for p in part), "longitude": ",".join(str(p[1]) for p in part),
                     "current": var}, timeout=40)
        data = data if isinstance(data, list) else [data]
        for j, item in enumerate(data):
            la, lo = part[j]
            out[lats.index(la), lons.index(lo)] = float(item["current"][var])
    return lats, lons, out
