"""Diário de bordo (SQLite) com exportação ADIF."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .settings import app_dir

BAND_ADIF = {"160m": "160M", "80m": "80M", "60m": "60M", "40m": "40M", "30m": "30M", "20m": "20M", "17m": "17M",
             "15m": "15M", "12m": "12M", "10m": "10M", "6m": "6M"}


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


class Logbook:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.db = sqlite3.connect(str(path or app_dir() / "log.db"), check_same_thread=False)
        self.db.execute("""create table if not exists qso (
            id integer primary key autoincrement, utc text, call text, freq integer, mode text,
            rst_sent text, rst_rcvd text, name text, grid text, country text, comment text)""")
        self.db.commit()

    def add(self, q: Qso) -> int:
        when = q.when or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur = self.db.execute(
            "insert into qso (utc, call, freq, mode, rst_sent, rst_rcvd, name, grid, country, comment) values (?,?,?,?,?,?,?,?,?,?)",
            (when, q.call.upper(), q.freq, q.mode, q.rst_sent, q.rst_rcvd, q.name, q.grid.upper(), q.country, q.comment))
        self.db.commit()
        return int(cur.lastrowid)

    def delete(self, qso_id: int) -> None:
        self.db.execute("delete from qso where id=?", (qso_id,))
        self.db.commit()

    def all(self, limit: int = 1000) -> list[Qso]:
        rows = self.db.execute(
            "select id, utc, call, freq, mode, rst_sent, rst_rcvd, name, grid, country, comment from qso order by id desc limit ?",
            (limit,)).fetchall()
        return [Qso(r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[1], r[0]) for r in rows]

    def worked(self, call: str) -> int:
        return self.db.execute("select count(*) from qso where call=?", (call.upper(),)).fetchone()[0]

    def export_adif(self, path: Path, band_for=None) -> int:
        qsos = list(reversed(self.all(100000)))
        out = ["ADIF export - IC-7300 App\n<EOH>\n"]
        for q in qsos:
            dt = datetime.strptime(q.when, "%Y-%m-%d %H:%M:%S")
            fields = {"CALL": q.call, "QSO_DATE": dt.strftime("%Y%m%d"), "TIME_ON": dt.strftime("%H%M%S"),
                      "FREQ": f"{q.freq / 1e6:.6f}", "MODE": _adif_mode(q.mode),
                      "RST_SENT": q.rst_sent, "RST_RCVD": q.rst_rcvd, "NAME": q.name,
                      "GRIDSQUARE": q.grid, "COUNTRY": q.country, "COMMENT": q.comment}
            if band_for and band_for(q.freq):
                fields["BAND"] = BAND_ADIF.get(band_for(q.freq), "")
            out.append("".join(f"<{k}:{len(v)}>{v} " for k, v in fields.items() if v) + "<EOR>\n")
        path.write_text("".join(out), encoding="utf-8")
        return len(qsos)


def _adif_mode(mode: str) -> str:
    return {"CW-R": "CW", "RTTY-R": "RTTY"}.get(mode, mode)
