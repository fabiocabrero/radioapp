"""Estações do mapa: fontes de relatos (PSK Reporter, WSPR, RBN, POTA, cluster) e as ações possíveis para cada indicativo.

Cada ponto do mapa é uma `Station`. `actions_for()` diz o que fazer com ela conforme o modo: sintonizar o rádio, abrir a
tela do app que decodifica aquele modo ou o programa externo certo (WSJT-X, JS8Call, VarAC, Winlink, Pat...).
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from . import geo, propagation

USER_AGENT = "IC7300App/0.1"
WSPR_URL = "https://db1.wspr.live/"
RBN_HOST = "telnet.reversebeacon.net"
RBN_PORT_CW_RTTY = 7000

SOURCES = {
    "spots": "DX Cluster",
    "pota": "POTA",
    "wwff": "WWFF",
    "ft8": "Decodificado aqui",
    "psk_tx": "PSK Reporter: me ouvem",
    "psk_rx": "PSK Reporter: eu ouço",
    "psk_band": "PSK Reporter: atividade",
    "wspr": "WSPR",
    "rbn": "Reverse Beacon Network",
    "busca": "Busca",
    "lista": "Lista importada",
    "sat": "Satélite amador (posição aproximada)",
}


@dataclass
class Station:
    call: str
    freq: int = 0                 # Hz; 0 quando não se sabe
    mode: str = ""
    source: str = "busca"
    lat: Optional[float] = None
    lon: Optional[float] = None
    grid: str = ""
    info: str = ""
    spotter: str = ""
    ref: str = ""                 # referência POTA/SOTA etc.
    stamp: float = field(default_factory=time.time)

    def label(self) -> str:
        parts = [self.call]
        if self.freq:
            parts.append(f"{self.freq / 1e6:.4f} MHz")
        if self.mode:
            parts.append(self.mode)
        if self.info:
            parts.append(self.info)
        return "  ".join(parts)


# ---------------------------------------------------------------------------------------------- modos
def mode_family(mode: str, freq: int = 0, info: str = "") -> str:
    """Agrupa o modo informado pela fonte em uma família: ft8, cw, rtty, wspr, js8, sstv, psk, phone, data, varac..."""
    m = (mode or "").upper().strip()
    text = f"{m} {info}".upper()
    if m in ("FT8", "FT4"):
        return "ft8"
    if m in ("FST4", "FST4W", "Q65", "JT65", "JT9", "MSK144"):
        return "wsjt"
    if m in ("WSPR", "WSPR-2", "WSPR-15"):
        return "wspr"
    if m.startswith("JS8"):
        return "js8"
    if m in ("CW", "CWT") or " CW " in f" {text} ":
        return "cw"
    if m in ("RTTY", "FSK", "RTTY-45"):
        return "rtty"
    if m.startswith("PSK") or m in ("BPSK31", "QPSK31", "OLIVIA", "MFSK", "CONTESTIA", "MT63", "THOR"):
        return "psk"
    if m in ("SSTV", "ROBOT"):
        return "sstv"
    if m in ("VARA", "VARA HF", "VARA FM", "VARAC", "ARDOP", "PACTOR", "PACKET", "ROBUST", "WINLINK"):
        return "winlink"
    if m in ("SSB", "USB", "LSB", "AM", "FM", "PHONE"):
        return "phone"
    if "FT8" in text:
        return "ft8"
    return "data" if m else "unknown"


def mode_for_radio(family: str, freq: int, mode: str = "") -> tuple[str, bool]:
    """(modo do rádio, usa DATA) para sintonizar uma estação daquela família."""
    sideband = "LSB" if freq < 10_000_000 else "USB"
    m = (mode or "").upper()
    if family == "cw":
        return "CW", False
    if family == "rtty":
        return "RTTY", False
    if family == "phone":
        return (m, False) if m in ("AM", "FM") else (sideband, False)
    if family in ("ft8", "wsjt", "wspr", "js8", "psk", "winlink", "data", "sstv"):
        return (sideband if family == "sstv" else "USB"), True
    return sideband, False


# ---------------------------------------------------------------------------------------------- ações
@dataclass(frozen=True)
class Action:
    key: str      # "tune", "page:ft8", "app:varac", "web:qrz", "copy"
    label: str
    hint: str = ""


# família -> ações recomendadas (as primeiras são as principais)
_FAMILY_ACTIONS: dict[str, tuple[Action, ...]] = {
    "ft8": (Action("page:ft8", "Abrir FT8/FT4 do app", "sintoniza o rádio e abre o decodificador/transmissor"),
            Action("app:wsjtx", "Abrir no WSJT-X", "ativa o rigctl, sintoniza e copia o indicativo"),
            Action("app:jtdx", "Abrir no JTDX")),
    "wsjt": (Action("page:wsjt", "Abrir FST4/Q65/WSPR do app"), Action("app:wsjtx", "Abrir no WSJT-X")),
    "wspr": (Action("page:wsjt", "Abrir WSPR (recepção) do app"), Action("app:wsjtx", "Abrir no WSJT-X")),
    "js8": (Action("app:js8call", "Abrir no JS8Call", "ativa o rigctl, sintoniza e copia o indicativo"),),
    "cw": (Action("page:cw", "Abrir o decodificador de CW"),),
    "rtty": (Action("page:rtty", "Abrir RTTY"), Action("app:fldigi", "Abrir no Fldigi")),
    "psk": (Action("app:fldigi", "Abrir no Fldigi (PSK31 e afins)"),),
    "sstv": (Action("page:sstv", "Abrir SSTV"), Action("app:mmsstv", "Abrir no MMSSTV")),
    "winlink": (Action("app:varac", "Conectar pelo VarAC", "copia o indicativo; cole no campo de conexão"),
                Action("app:winlink_express", "Conectar pelo Winlink Express"),
                Action("app:pat", "Conectar pelo Pat")),
    "phone": (Action("page:radio", "Ouvir no rádio", "sintoniza e abre a tela do rádio"),),
    "data": (Action("page:radio", "Sintonizar no rádio"),),
    "unknown": (Action("page:radio", "Sintonizar no rádio"),),
}

# ferramentas de conexão que servem para qualquer indicativo, em ordem
CONNECT_APPS: tuple[Action, ...] = (
    Action("app:varac", "VarAC (chat VARA HF)"),
    Action("app:winlink_express", "Winlink Express"),
    Action("app:pat", "Pat (Winlink)"),
    Action("app:js8call", "JS8Call"),
    Action("app:wsjtx", "WSJT-X"),
    Action("app:fldigi", "Fldigi"),
)

WEB_ACTIONS: tuple[Action, ...] = (
    Action("web:kiwi", "Ouvir num SDR público (KiwiSDR)", "abre o mapa de receptores KiwiSDR no navegador"),
    Action("web:websdr", "Ouvir num WebSDR", "abre o diretório WebSDR no navegador"),
    Action("web:qrz", "Ver no QRZ.com"),
    Action("web:hamqth", "Ver no HamQTH"),
    Action("web:psk", "Ver no PSK Reporter"),
)


def actions_for(st: Station) -> tuple[list[Action], list[Action]]:
    """(principais, outras) para a estação. Principais dependem do modo; outras são as ferramentas gerais."""
    if st.source == "sat":
        return [], [Action("web:amsat", "Status dos satélites (AMSAT)"), Action("copy", "Copiar nome")]
    family = mode_family(st.mode, st.freq, st.info)
    main = list(_FAMILY_ACTIONS.get(family, _FAMILY_ACTIONS["unknown"]))
    if st.freq and family not in ("phone", "data", "unknown") and not any(a.key == "tune" for a in main):
        main.append(Action("tune", "Só sintonizar o rádio"))
    if st.source in ("pota", "wwff") and st.ref:
        main.append(Action("pota", f"Marcar {st.ref} para o log", "guarda a referência no log"))
    if not st.freq:  # sem frequência (busca por indicativo): só as ferramentas de conexão
        main = []
    used = {a.key for a in main}
    other = [a for a in CONNECT_APPS if a.key not in used] + list(WEB_ACTIONS)
    other.append(Action("copy", "Copiar indicativo"))
    return main, other


def web_url(kind: str, call: str) -> str:
    call = urllib.parse.quote(call.upper().split("-")[0].replace("#", ""))
    return {"qrz": f"https://www.qrz.com/db/{call}", "hamqth": f"https://www.hamqth.com/{call}",
            "psk": f"https://pskreporter.info/pskmap.html?callsign={call}", "amsat": "https://www.amsat.org/status/",
            "kiwi": "https://rx.kiwisdr.com/", "websdr": "https://websdr.org/"}[kind]


# ---------------------------------------------------------------------------------------------- RBN / cluster
_RBN_INFO = re.compile(r"^(?P<mode>CW|RTTY|PSK\d*|FT8|FT4|JS8|MSK144)\s+(?P<snr>-?\d+)\s*dB", re.I)


def split_cluster_info(info: str) -> tuple[str, str]:
    """('FT8', '+5 dB ...') a partir do comentário de um spot do RBN ou do cluster."""
    m = _RBN_INFO.match(info.strip())
    if m:
        return m.group("mode").upper(), info.strip()
    for token in re.split(r"[\s,;]+", info.upper()):
        if token in ("CW", "RTTY", "FT8", "FT4", "JS8", "SSB", "PSK31", "FM", "AM"):
            return token, info.strip()
    return "", info.strip()


# ---------------------------------------------------------------------------------------------- PSK Reporter
def fetch_psk_band(low_hz: int, high_hz: int, mode: str = "", seconds: int = 900, limit: int = 400,
                   timeout: float = 30) -> list[Station]:
    """Atividade em uma faixa de frequências (e modo opcional): quem está transmitindo e foi ouvido.

    A API do PSK Reporter aceita frange, mode, flowStartSeconds e rptlimit; pede no máximo uma consulta a cada 5 minutos.
    """
    q = {"frange": f"{int(low_hz)}-{int(high_hz)}", "flowStartSeconds": f"-{int(seconds)}", "rptlimit": str(int(limit)),
         "rronly": "1", "appcontact": "ic7300app"}
    if mode:
        q["mode"] = mode
    req = urllib.request.Request(f"{propagation.PSK_URL}?{urllib.parse.urlencode(q)}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return psk_reports_to_stations(propagation.parse_psk(resp.read().decode("utf-8", "replace")))


def psk_reports_to_stations(reports: list[propagation.Report]) -> list[Station]:
    seen: dict[str, Station] = {}
    for r in reports:
        try:
            lat, lon = geo.grid_to_latlon(r.sender_grid[:6] if len(r.sender_grid) >= 6 else r.sender_grid[:4])
        except ValueError:
            continue
        old = seen.get(r.sender)
        if old and old.stamp >= r.when:
            continue
        seen[r.sender] = Station(r.sender, r.freq, r.mode, "psk_band", lat, lon, r.sender_grid,
                                 f"{r.snr:+d} dB ouvido por {r.receiver}", r.receiver, stamp=float(r.when) or time.time())
    return list(seen.values())


# ---------------------------------------------------------------------------------------------- WSPR
def wspr_query(seconds: int = 1800, band: Optional[int] = None, limit: int = 300) -> str:
    where = f"time > now() - INTERVAL {int(seconds)} SECOND"
    if band is not None:
        where += f" AND band = {int(band)}"
    return ("SELECT time, tx_sign, tx_loc, tx_lat, tx_lon, frequency, snr, rx_sign FROM wspr.rx "
            f"WHERE {where} ORDER BY time DESC LIMIT {int(limit)} FORMAT JSON")


def parse_wspr(payload: dict) -> list[Station]:
    seen: dict[str, Station] = {}
    for row in payload.get("data", []):
        try:
            call = row["tx_sign"]
            if call in seen:
                continue
            seen[call] = Station(call, int(row["frequency"]), "WSPR", "wspr", float(row["tx_lat"]), float(row["tx_lon"]),
                                 row.get("tx_loc", ""), f"{int(row['snr']):+d} dB ouvido por {row.get('rx_sign', '')}",
                                 row.get("rx_sign", ""))
        except (KeyError, ValueError, TypeError):
            continue
    return list(seen.values())


def fetch_wspr(seconds: int = 1800, band: Optional[int] = None, timeout: float = 30) -> list[Station]:
    """Spots do WSPR via wspr.live (leitura pública, 20 consultas por minuto, uso não comercial)."""
    url = WSPR_URL + "?" + urllib.parse.urlencode({"query": wspr_query(seconds, band)})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_wspr(json.load(resp))


# ---------------------------------------------------------------------------------------------- listas importadas
# Para fontes que bloqueiam acesso automático (ex.: lista de gateways do Winlink) ou que o usuário baixa em arquivo:
# o app lê CSV/TSV com cabeçalho ou texto solto (uma estação por linha) e põe as estações no mapa.
_CALL_RE = re.compile(r"\b[A-Z0-9]{1,2}\d[A-Z]{1,4}(?:-\d{1,2})?\b")
_GRID_RE = re.compile(r"\b[A-R]{2}\d{2}(?:[A-X]{2})?\b", re.I)
_MODE_WORDS = ("VARA FM", "VARA HF", "VARA", "ARDOP", "PACTOR", "PACKET", "ROBUST", "WINLINK", "FT8", "FT4", "JS8",
               "CW", "RTTY", "PSK31", "SSB", "FM", "AM", "D-STAR", "DMR", "C4FM")
_ALIASES = {
    "call": ("call", "callsign", "indicativo", "gateway", "station", "sign"),
    "freq": ("freq", "frequency", "frequencia", "frequência", "output", "dial", "center", "centro", "khz", "mhz"),
    "mode": ("mode", "modo", "protocol", "protocolo"),
    "grid": ("grid", "locator", "loc", "gridsquare", "maidenhead"),
    "lat": ("lat", "latitude"),
    "lon": ("lon", "lng", "long", "longitude"),
    "info": ("name", "nome", "city", "cidade", "location", "local", "notes", "obs", "comment", "hours", "horario"),
}


def normalize_freq(value: str, unit_hint: str = "") -> int:
    """Hz a partir de '7.1015' (MHz), '14101.5' (kHz) ou '14101500' (Hz); 0 se não for número."""
    try:
        v = float(value.replace(",", ".").strip())
    except ValueError:
        return 0
    if unit_hint == "khz":
        return int(round(v * 1e3))
    if unit_hint == "mhz":
        return int(round(v * 1e6))
    if v < 1000:
        return int(round(v * 1e6))
    if v < 100_000:
        return int(round(v * 1e3))
    return int(round(v))


def _find_mode(text: str) -> str:
    up = text.upper()
    return next((m for m in _MODE_WORDS if re.search(rf"(?<![A-Z0-9]){re.escape(m)}(?![A-Z0-9])", up)), "")


def parse_station_list(text: str, source: str = "lista", default_mode: str = "") -> list[Station]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    delim = next((d for d in ("\t", ";", ",") if d in lines[0]), "")
    cols: dict[str, int] = {}
    if delim:
        heads = [h.strip().lower() for h in lines[0].split(delim)]
        for key, names in _ALIASES.items():
            for i, h in enumerate(heads):
                if any(h == n or h.startswith(n) for n in names):
                    cols.setdefault(key, i)
                    break
    out: list[Station] = []
    if "call" in cols:
        hint = ""
        if "freq" in cols:
            h = lines[0].split(delim)[cols["freq"]].lower()
            hint = "khz" if "khz" in h else ("mhz" if "mhz" in h else "")
        for ln in lines[1:]:
            f = [x.strip() for x in ln.split(delim)]
            def get(k: str, row: list = f) -> str:
                return row[cols[k]] if k in cols and cols[k] < len(row) else ""

            call = get("call").upper()
            if not _CALL_RE.fullmatch(call):
                continue
            st = Station(call, normalize_freq(get("freq"), hint), get("mode").upper() or default_mode, source,
                         info=get("info"), grid=get("grid"))
            try:
                st.lat, st.lon = float(get("lat")), float(get("lon"))
            except ValueError:
                pass
            out.append(st)
    else:  # texto solto: indicativo, grid, frequência e modo achados na linha
        for ln in lines:
            m = _CALL_RE.search(ln.upper())
            if not m:
                continue
            rest = ln.upper().replace(m.group(0), " ", 1)
            grid = _GRID_RE.search(rest)
            if grid:
                rest = rest.replace(grid.group(0), " ", 1)
            freq = next((normalize_freq(t) for t in re.findall(r"\d+(?:[.,]\d+)?", rest) if normalize_freq(t) >= 100_000), 0)
            out.append(Station(m.group(0), freq, _find_mode(rest) or default_mode, source, grid=grid.group(0) if grid else "",
                               info=""))
    for st in out:
        if st.grid and st.lat is None:
            try:
                st.lat, st.lon = geo.grid_to_latlon(st.grid[:6] if len(st.grid) >= 6 else st.grid[:4])
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------------------------------------- WWFF
WWFF_URL = "https://spots.wwff.co/static/spots.json"
WWFF_AGENT = "IC7300App/0.1 (+https://github.com/fabiocabrero/radioapp)"  # a WWFF pede User-Agent descritivo com contato


def parse_wwff(payload: list, max_age_s: int = 3600, now: Optional[float] = None) -> list[Station]:
    """Spots recentes do WWFF (uma estação por ativador, o mais novo)."""
    now = now or time.time()
    seen: dict[str, Station] = {}
    for s in payload:
        try:
            call = s["activator"]
            stamp = float(s["spot_time"])
            if now - stamp > max_age_s or call in seen:
                continue
            ref = s.get("reference", "")
            seen[call] = Station(call, int(round(float(s["frequency_khz"]) * 1000)), (s.get("mode") or "").upper(), "wwff",
                                 s.get("latitude"), s.get("longitude"),
                                 info=f"{ref} {s.get('reference_name', '')}".strip() + (f" · {s['remarks']}" if s.get("remarks") else ""),
                                 spotter=s.get("spotter", ""), ref=ref, stamp=stamp)
        except (KeyError, ValueError, TypeError):
            continue
    return list(seen.values())


def fetch_wwff(timeout: float = 20) -> list[Station]:
    """Spots do WWFF Spotline (leitura pública sem chave; no máximo 1 consulta a cada 30 s)."""
    req = urllib.request.Request(WWFF_URL, headers={"User-Agent": WWFF_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_wwff(json.load(resp))
