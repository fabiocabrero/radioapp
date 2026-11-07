"""Clima espacial do NOAA SWPC (domínio público, sem chave): índice Kp, boletins de alerta, aurora e absorção na região D."""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field

BASE = "https://services.swpc.noaa.gov/"
USER_AGENT = "IC7300App/0.1 (+https://github.com/fabiocabrero/radioapp)"


@dataclass
class Alert:
    code: str       # A20F, K04W, EF3A...
    issued: str     # "2026-11-07 06:26"
    headline: str   # "WATCH: Geomagnetic Storm Category G1 Predicted"
    severity: str   # watch | warning | alert | summary | other


@dataclass
class SpaceWeather:
    kp: float = 0.0
    kp_time: str = ""
    kp_series: list = field(default_factory=list)   # últimos valores de 3 h
    alerts: list = field(default_factory=list)


def _get(path: str, timeout: float = 20):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_kp(rows: list) -> tuple[float, str, list]:
    vals = []
    for r in rows:
        try:
            vals.append((r["time_tag"], float(r["Kp"])))
        except (KeyError, ValueError, TypeError):
            continue
    if not vals:
        return 0.0, "", []
    return vals[-1][1], vals[-1][0].replace("T", " ")[:16], [v for _, v in vals[-16:]]


_HEAD = re.compile(r"^(WATCH|WARNING|ALERT|SUMMARY|EXTENDED WARNING|CONTINUED ALERT|CANCEL WATCH):\s*(.+)$", re.M)


def parse_alerts(rows: list, limit: int = 6) -> list[Alert]:
    out = []
    for r in rows:
        try:
            msg = r["message"].replace("\r", "")
            m = _HEAD.search(msg)
            kind, text = (m.group(1), m.group(2).strip()) if m else ("", (msg.strip().splitlines() or [""])[-1])
            sev = kind.split()[-1].lower() if kind else "other"
            out.append(Alert(r.get("product_id", ""), r.get("issue_datetime", "")[:16], f"{kind}: {text}".strip(": "),
                             sev if sev in ("watch", "warning", "alert", "summary") else "other"))
        except (KeyError, TypeError, AttributeError):
            continue
        if len(out) >= limit:
            break
    return out


def fetch_spacewx() -> SpaceWeather:
    sw = SpaceWeather()
    sw.kp, sw.kp_time, sw.kp_series = parse_kp(json.loads(_get("products/noaa-planetary-k-index.json")))
    sw.alerts = parse_alerts(json.loads(_get("products/alerts.json")))
    return sw


def parse_drap(text: str):
    """Absorção da região D (D-RAP): (lats, lons, matriz[lat][lon]) em MHz, a frequência com 1 dB de absorção."""
    import numpy as np

    lons = lats = None
    rows = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip() or line.startswith("---"):
            continue
        if "|" not in line:
            lons = np.array([float(x) for x in line.split()])
            continue
        head, vals = line.split("|", 1)
        lats = (lats or []) + [float(head)]
        rows.append([float(x) for x in vals.split()])
    if lons is None or not rows:
        raise ValueError("D-RAP sem dados")
    order = np.argsort(lats)
    return np.array(lats)[order], lons, np.array(rows, dtype=np.float32)[order]


def fetch_drap():
    return parse_drap(_get("text/drap_global_frequencies.txt").decode("utf-8", "replace"))


def parse_aurora(payload: dict):
    """Grade de aurora (probabilidade 0-100) como matriz [lat -90..90][lon 0..359] e o horário da previsão."""
    import numpy as np

    grid = np.zeros((181, 360), dtype=np.float32)
    for lon, lat, val in payload.get("coordinates", []):
        if 0 <= lon < 360 and -90 <= lat <= 90:
            grid[int(lat) + 90, int(lon)] = val
    return grid, str(payload.get("Forecast Time", ""))


def fetch_aurora():
    return parse_aurora(json.loads(_get("json/ovation_aurora_latest.json", timeout=40)))
