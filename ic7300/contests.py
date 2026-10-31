"""Calendário de concursos (WA7BNM, via RSS), log de concurso e exportação Cabrillo."""
from __future__ import annotations

import re
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .settings import app_dir

CALENDAR_URL = "https://www.contestcalendar.com/calendar.rss"
_MONTHS = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_RANGE = re.compile(r"(\d{4})Z, ([A-Z][a-z]{2}) (\d{1,2}) to (\d{4})Z, ([A-Z][a-z]{2}) (\d{1,2})")
_SAME_DAY = re.compile(r"(\d{4})Z-(\d{4})Z, ([A-Z][a-z]{2}) (\d{1,2})(?: \(([^)]+)\))?")
_MODE_WORDS = [("CW", "CW"), ("SSB", "SSB"), ("PHONE", "SSB"), ("RTTY", "RTTY"), ("DIGI", "Digital"), ("FT8", "Digital"),
               ("FT4", "Digital"), ("PSK", "Digital"), ("FM", "FM"), ("EME", "EME")]


@dataclass
class Window:
    start: datetime
    end: datetime
    label: str = ""


@dataclass
class Contest:
    title: str
    link: str
    windows: list[Window] = field(default_factory=list)

    def mode(self) -> str:
        up = self.title.upper()
        return next((m for word, m in _MODE_WORDS if word in up), "Misto")

    def running(self, now: datetime) -> Optional[Window]:
        return next((w for w in self.windows if w.start <= now < w.end), None)

    def next_window(self, now: datetime) -> Optional[Window]:
        future = [w for w in self.windows if w.start > now]
        return min(future, key=lambda w: w.start) if future else None


def _dt(year: int, month: str, day: int, hhmm: str) -> datetime:
    return datetime(year, _MONTHS[month], day, int(hhmm[:2]) % 24, int(hhmm[2:]), tzinfo=timezone.utc) + (
        timedelta(days=1) if hhmm == "2400" else timedelta())


def parse_windows(desc: str, ref: datetime) -> list[Window]:
    """Interpreta as janelas ('0000Z-0400Z, Nov 1', '1200Z, Oct 31 to 1200Z, Nov 1', combinações com 'and')."""
    out: list[Window] = []
    for part in desc.split(" and "):
        try:
            m = _RANGE.search(part)
            if m:
                year = _year_for(m.group(2), ref)
                start = _dt(year, m.group(2), int(m.group(3)), m.group(1))
                end = _dt(_year_for(m.group(5), ref), m.group(5), int(m.group(6)), m.group(4))
                if end < start and (start - end) > timedelta(days=200):
                    end = end.replace(year=end.year + 1)
                label = ""
            else:
                m = _SAME_DAY.search(part)
                if not m:
                    continue
                year = _year_for(m.group(3), ref)
                start = _dt(year, m.group(3), int(m.group(4)), m.group(1))
                end = _dt(year, m.group(3), int(m.group(4)), m.group(2))
                if end <= start:
                    end += timedelta(days=1)
                label = m.group(5) or ""
        except (KeyError, ValueError):
            continue
        if end > start and end - start <= timedelta(days=4):  # descarta datas obviamente erradas do calendário
            out.append(Window(start, end, label))
    return out


def _year_for(month: str, ref: datetime) -> int:
    m = _MONTHS[month]
    if m < ref.month - 6:
        return ref.year + 1
    if m > ref.month + 6:
        return ref.year - 1
    return ref.year


def parse_calendar(xml_text: str, ref: Optional[datetime] = None) -> list[Contest]:
    root = ET.fromstring(xml_text)
    if ref is None:
        built = root.findtext("channel/lastBuildDate") or ""
        try:
            ref = datetime.strptime(built[:25], "%a, %d %b %Y %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            ref = datetime.now(timezone.utc)
    contests = []
    for item in root.iter("item"):
        windows = parse_windows((item.findtext("description") or "").strip(), ref)
        if windows:
            contests.append(Contest((item.findtext("title") or "").strip(), (item.findtext("link") or "").strip(), windows))
    return contests


def fetch_calendar(timeout: float = 20) -> list[Contest]:
    req = urllib.request.Request(CALENDAR_URL, headers={"User-Agent": "IC7300App/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_calendar(resp.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------- log de concurso
_CABRILLO_MODE = {"CW": "CW", "CW-R": "CW", "LSB": "PH", "USB": "PH", "AM": "PH", "FM": "FM", "RTTY": "RY", "RTTY-R": "RY"}


@dataclass
class ContestQso:
    call: str
    freq: int
    mode: str            # modo do rádio (USB, CW, ...) ou FT8/FT4/RTTY
    rst_sent: str = "59"
    exch_sent: str = ""
    rst_rcvd: str = "59"
    exch_rcvd: str = ""
    when: str = ""       # "YYYY-MM-DD HH:MM:SS" UTC
    dupe: bool = False
    id: Optional[int] = None


def cabrillo_mode(mode: str) -> str:
    if mode in _CABRILLO_MODE:
        return _CABRILLO_MODE[mode]
    return "DG" if mode.upper() in ("FT8", "FT4", "JS8", "DIGI", "PSK31") else "PH"


def band_of(freq_hz: int) -> str:
    """Banda amadora pelo limite superior, para a checagem de duplicados."""
    edges = [(2_000_000, "160"), (4_000_000, "80"), (5_500_000, "60"), (7_500_000, "40"), (10_200_000, "30"),
             (14_500_000, "20"), (18_200_000, "17"), (21_500_000, "15"), (25_000_000, "12"), (30_000_000, "10"),
             (60_000_000, "6")]
    return next((name for edge, name in edges if freq_hz < edge), "VHF")


class ContestLog:
    """Log de um concurso, na mesma base SQLite do diário."""

    def __init__(self, contest: str, path: Optional[Path] = None) -> None:
        self.contest = contest
        self.db = sqlite3.connect(str(path or app_dir() / "log.db"), check_same_thread=False)
        self.db.execute("""create table if not exists contest_qso (
            id integer primary key autoincrement, contest text, utc text, call text, freq integer, mode text,
            rst_sent text, exch_sent text, rst_rcvd text, exch_rcvd text, band text, cmode text, dupe integer default 0)""")
        self.db.commit()

    def is_dupe(self, call: str, freq: int, mode: str) -> bool:
        row = self.db.execute("select count(*) from contest_qso where contest=? and call=? and band=? and cmode=? and dupe=0",
                              (self.contest, call.upper(), band_of(freq), cabrillo_mode(mode))).fetchone()
        return row[0] > 0

    def add(self, q: ContestQso) -> ContestQso:
        q.call = q.call.strip().upper()
        q.dupe = self.is_dupe(q.call, q.freq, q.mode)
        q.when = q.when or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur = self.db.execute(
            "insert into contest_qso (contest, utc, call, freq, mode, rst_sent, exch_sent, rst_rcvd, exch_rcvd, band, cmode, dupe) "
            "values (?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.contest, q.when, q.call, q.freq, q.mode, q.rst_sent, q.exch_sent, q.rst_rcvd, q.exch_rcvd,
             band_of(q.freq), cabrillo_mode(q.mode), int(q.dupe)))
        self.db.commit()
        q.id = int(cur.lastrowid)
        return q

    def delete(self, qso_id: int) -> None:
        self.db.execute("delete from contest_qso where id=?", (qso_id,))
        self.db.commit()

    def all(self) -> list[ContestQso]:
        rows = self.db.execute(
            "select id, utc, call, freq, mode, rst_sent, exch_sent, rst_rcvd, exch_rcvd, dupe from contest_qso "
            "where contest=? order by id", (self.contest,)).fetchall()
        return [ContestQso(r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[1], bool(r[9]), r[0]) for r in rows]

    def next_serial(self) -> int:
        return self.db.execute("select count(*) from contest_qso where contest=? and dupe=0", (self.contest,)).fetchone()[0] + 1

    def stats(self, cty=None) -> dict:
        qsos = self.all()
        valid = [q for q in qsos if not q.dupe]
        out = {"qsos": len(valid), "dupes": len(qsos) - len(valid)}
        bands: dict[str, int] = {}
        for q in valid:
            bands[band_of(q.freq)] = bands.get(band_of(q.freq), 0) + 1
        out["bands"] = bands
        if cty:
            ents = [cty.lookup(q.call) for q in valid]
            ents = [e for e in ents if e]
            out["dxcc"] = len({e.name for e in ents})
            out["cq_zones"] = len({e.cq for e in ents})
        return out

    def export_cabrillo(self, callsign: str, header: dict, cabrillo_id: str = "") -> str:
        """Cabrillo 3.0. As categorias e a troca variam por concurso: confira as regras antes de enviar."""
        lines = ["START-OF-LOG: 3.0", "CREATED-BY: IC-7300 Station", f"CALLSIGN: {callsign.upper()}",
                 f"CONTEST: {cabrillo_id or self.contest}"]
        for key in ("CATEGORY-OPERATOR", "CATEGORY-BAND", "CATEGORY-MODE", "CATEGORY-POWER", "CATEGORY-ASSISTED",
                    "CLAIMED-SCORE", "OPERATORS", "CLUB", "LOCATION", "NAME", "ADDRESS", "ADDRESS-CITY",
                    "ADDRESS-STATE-PROVINCE", "ADDRESS-POSTALCODE", "ADDRESS-COUNTRY", "EMAIL", "SOAPBOX"):
            value = str(header.get(key, "")).strip()
            if value:
                lines.append(f"{key}: {value}")
        for q in self.all():
            dt = datetime.strptime(q.when, "%Y-%m-%d %H:%M:%S")
            lines.append("QSO: {:>5} {:<2} {} {} {:<13} {:<3} {:<6} {:<13} {:<3} {:<6}".format(
                q.freq // 1000, cabrillo_mode(q.mode), dt.strftime("%Y-%m-%d"), dt.strftime("%H%M"), callsign.upper(),
                q.rst_sent, q.exch_sent, q.call, q.rst_rcvd, q.exch_rcvd).rstrip())
        lines.append("END-OF-LOG:")
        return "\n".join(lines) + "\n"
