"""Diário de bordo (SQLite) com exportação ADIF e referências POTA/SOTA/WWFF."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .settings import app_dir

BAND_ADIF = {"160m": "160M", "80m": "80M", "60m": "60M", "40m": "40M", "30m": "30M", "20m": "20M", "17m": "17M",
             "15m": "15M", "12m": "12M", "10m": "10M", "6m": "6M"}

_POTA = re.compile(r"^[A-Z0-9]{1,3}-\d{4,5}$")
_SOTA = re.compile(r"^[A-Z0-9]{1,3}/[A-Z]{2}-\d{3}$")
_WWFF = re.compile(r"^[A-Z0-9]{1,4}FF-\d{4}$")


def ref_kind(ref: str) -> str:
    """'POTA', 'SOTA', 'WWFF' ou '' conforme o formato da referência."""
    ref = ref.strip().upper()
    if _WWFF.match(ref):
        return "WWFF"
    if _SOTA.match(ref):
        return "SOTA"
    if _POTA.match(ref):
        return "POTA"
    return ""


@dataclass
class Qso:
    call: str
    freq: int
    mode: str
    rst_sent: str = "59"
    rst_rcvd: str = "59"
    name: str = ""
    grid: str = ""
    country: str = ""
    comment: str = ""
    when: str = ""
    id: Optional[int] = None
    ref: str = ""      # referência da estação contatada (parque, cume): hunter
    my_ref: str = ""   # minha referência quando ativo (parque, cume): ativador


class Logbook:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.db = sqlite3.connect(str(path or app_dir() / "log.db"), check_same_thread=False)
        self.db.execute("""create table if not exists qso (
            id integer primary key autoincrement, utc text, call text, freq integer, mode text,
            rst_sent text, rst_rcvd text, name text, grid text, country text, comment text)""")
        cols = {r[1] for r in self.db.execute("pragma table_info(qso)")}
        for col in ("ref", "my_ref"):
            if col not in cols:
                self.db.execute(f"alter table qso add column {col} text default ''")
        self.db.commit()

    def add(self, q: Qso) -> int:
        when = q.when or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur = self.db.execute(
            "insert into qso (utc, call, freq, mode, rst_sent, rst_rcvd, name, grid, country, comment, ref, my_ref) "
            "values (?,?,?,?,?,?,?,?,?,?,?,?)",
            (when, q.call.upper(), q.freq, q.mode, q.rst_sent, q.rst_rcvd, q.name, q.grid.upper(), q.country, q.comment,
             q.ref.strip().upper(), q.my_ref.strip().upper()))
        self.db.commit()
        return int(cur.lastrowid)

    def delete(self, qso_id: int) -> None:
        self.db.execute("delete from qso where id=?", (qso_id,))
        self.db.commit()

    def all(self, limit: int = 1000, my_ref: str = "") -> list[Qso]:
        sql = ("select id, utc, call, freq, mode, rst_sent, rst_rcvd, name, grid, country, comment, "
               "coalesce(ref, ''), coalesce(my_ref, '') from qso")
        args: tuple = ()
        if my_ref:
            sql += " where my_ref=?"
            args = (my_ref.upper(),)
        rows = self.db.execute(sql + " order by id desc limit ?", args + (limit,)).fetchall()
        return [Qso(r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[1], r[0], r[11], r[12]) for r in rows]

    def worked(self, call: str) -> int:
        return self.db.execute("select count(*) from qso where call=?", (call.upper(),)).fetchone()[0]

    def worked_ref(self, call: str, ref: str) -> bool:
        return self.db.execute("select count(*) from qso where call=? and ref=?", (call.upper(), ref.upper())).fetchone()[0] > 0

    def activation_count(self, my_ref: str, day: Optional[str] = None) -> int:
        """QSOs do dia (UTC) feitos como ativador da referência; POTA exige 10 para validar a ativação."""
        day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.db.execute("select count(*) from qso where my_ref=? and utc like ?",
                               (my_ref.upper(), day + "%")).fetchone()[0]

    def export_adif(self, path: Path, band_for=None, my_ref: str = "", my_call: str = "") -> int:
        qsos = list(reversed(self.all(100000, my_ref)))
        out = ["ADIF export - IC-7300 App\n<ADIF_VER:5>3.1.4\n<PROGRAMID:12>IC7300 Station\n<EOH>\n"]
        for q in qsos:
            dt = datetime.strptime(q.when, "%Y-%m-%d %H:%M:%S")
            fields = {"CALL": q.call, "QSO_DATE": dt.strftime("%Y%m%d"), "TIME_ON": dt.strftime("%H%M%S"),
                      "FREQ": f"{q.freq / 1e6:.6f}", "MODE": _adif_mode(q.mode),
                      "RST_SENT": q.rst_sent, "RST_RCVD": q.rst_rcvd, "NAME": q.name,
                      "GRIDSQUARE": q.grid, "COUNTRY": q.country, "COMMENT": q.comment}
            if my_call:
                fields["STATION_CALLSIGN"] = my_call.upper()
                fields["OPERATOR"] = my_call.upper()
            if band_for and band_for(q.freq):
                fields["BAND"] = BAND_ADIF.get(band_for(q.freq), "")
            for ref, prefix in ((q.ref, ""), (q.my_ref, "MY_")):
                kind = ref_kind(ref)
                if kind:
                    fields[f"{prefix}{kind}_REF"] = ref.upper()
            out.append("".join(f"<{k}:{len(v)}>{v} " for k, v in fields.items() if v) + "<EOR>\n")
        path.write_text("".join(out), encoding="utf-8")
        return len(qsos)


def _adif_mode(mode: str) -> str:
    return {"CW-R": "CW", "RTTY-R": "RTTY"}.get(mode, mode)
