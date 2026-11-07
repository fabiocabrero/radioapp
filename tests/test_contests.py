from datetime import datetime, timezone


from ic7300 import contests
from ic7300.logbook import Logbook, Qso, ref_kind

NOW = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?><rss><channel><lastBuildDate>Sat, 31 Oct 2026 00:00:00 +0000</lastBuildDate>
<item><title>UK/EI DX Contest, SSB</title><link>http://x/1</link><description>1200Z, Oct 31 to 1200Z, Nov 1</description></item>
<item><title>NA SSB Sprint</title><link>http://x/2</link><description>0000Z-0400Z, Nov 1</description></item>
<item><title>Walk for the Bacon QRP</title><link>http://x/3</link><description>0000Z-0100Z, Nov 5 and 0200Z-0300Z, Nov 6</description></item>
<item><title>NRAU 10m</title><link>http://x/4</link><description>1800Z-1900Z, Nov 5 (CW) and 1900Z-2000Z, Nov 5 (SSB)</description></item>
<item><title>Classic Exchange CW</title><link>http://x/5</link><description>1400Z, Nov 1 to 0800Z, Nov 2 and 1400Z, Mar 3 to 0800Z, Nov 4</description></item>
<item><title>Year Wrap</title><link>http://x/6</link><description>2100Z-0100Z, Dec 31</description></item>
<item><title>Lixo</title><link>http://x/7</link><description>sem data</description></item>
</channel></rss>"""


def test_calendar_parsing_and_status():
    cs = {c.title: c for c in contests.parse_calendar(RSS)}
    assert "Lixo" not in cs
    uk = cs["UK/EI DX Contest, SSB"]
    assert uk.running(NOW) is not None and uk.mode() == "SSB"
    sprint = cs["NA SSB Sprint"]
    assert sprint.running(NOW) is None
    assert sprint.next_window(NOW).start == datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    assert len(cs["Walk for the Bacon QRP"].windows) == 2
    assert [w.label for w in cs["NRAU 10m"].windows] == ["CW", "SSB"]
    assert len(cs["Classic Exchange CW"].windows) == 1  # a janela com data errada do calendário foi descartada
    wrap = cs["Year Wrap"].windows[0]
    assert wrap.end == datetime(2027, 1, 1, 1, 0, tzinfo=timezone.utc)


def test_contest_log_dupes_serial_and_cabrillo(tmp_path):
    log = contests.ContestLog("TESTE", tmp_path / "c.db")
    assert log.next_serial() == 1
    a = log.add(contests.ContestQso("W1AW", 14_250_000, "USB", "59", "001", "59", "05", "2026-11-01 01:23:00"))
    assert not a.dupe and log.next_serial() == 2
    b = log.add(contests.ContestQso("w1aw", 14_260_000, "LSB", "59", "002", "59", "05", "2026-11-01 01:25:00"))
    assert b.dupe and log.next_serial() == 2                               # mesma banda e modo (PH): duplicado
    c = log.add(contests.ContestQso("W1AW", 7_150_000, "LSB", "59", "002", "59", "05", "2026-11-01 01:30:00"))
    assert not c.dupe                                                        # outra banda vale
    d = log.add(contests.ContestQso("W1AW", 14_030_000, "CW", "599", "003", "599", "05", "2026-11-01 01:40:00"))
    assert not d.dupe                                                        # outro modo vale
    st = log.stats()
    assert st["qsos"] == 3 and st["dupes"] == 1
    text = log.export_cabrillo("PY2XX", {"CATEGORY-OPERATOR": "SINGLE-OP", "NAME": "Fabio"}, "CQ-WW-SSB")
    lines = text.splitlines()
    assert lines[0] == "START-OF-LOG: 3.0" and lines[-1] == "END-OF-LOG:"
    assert "CONTEST: CQ-WW-SSB" in lines and "CATEGORY-OPERATOR: SINGLE-OP" in lines
    q1 = next(l for l in lines if l.startswith("QSO:") and "14250" in l)
    assert q1 == "QSO: 14250 PH 2026-11-01 0123 PY2XX         59  001    W1AW          59  05"
    assert sum(1 for l in lines if l.startswith("QSO:")) == 4


def test_references_and_adif(tmp_path):
    assert ref_kind("br-0123") == "POTA" and ref_kind("G/LD-001") == "SOTA" and ref_kind("PYFF-0012") == "WWFF"
    assert ref_kind("xyz") == ""
    log = Logbook(tmp_path / "l.db")
    log.add(Qso("W1AW", 14_074_000, "FT8", ref="US-0001", my_ref="BR-0123", when="2026-11-01 12:00:00"))
    log.add(Qso("K1ABC", 7_200_000, "LSB", my_ref="BR-0123", when="2026-11-01 12:05:00"))
    log.add(Qso("N0XYZ", 7_200_000, "LSB", when="2026-11-01 12:06:00"))
    assert log.worked_ref("w1aw", "us-0001") and not log.worked_ref("K1ABC", "US-0001")
    assert log.activation_count("BR-0123", "2026-11-01") == 2
    out = tmp_path / "a.adi"
    assert log.export_adif(out, my_ref="BR-0123", my_call="PY2XX") == 2
    text = out.read_text(encoding="utf-8")
    assert "<MY_POTA_REF:7>BR-0123" in text and "<POTA_REF:7>US-0001" in text and "<STATION_CALLSIGN:5>PY2XX" in text
    assert "N0XYZ" not in text


def test_old_database_is_migrated(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("""create table qso (id integer primary key autoincrement, utc text, call text, freq integer, mode text,
        rst_sent text, rst_rcvd text, name text, grid text, country text, comment text)""")
    db.execute("insert into qso (utc, call, freq, mode) values ('2026-10-01 10:00:00', 'W1AW', 14074000, 'FT8')")
    db.commit()
    db.close()
    log = Logbook(path)
    assert log.all()[0].call == "W1AW" and log.all()[0].ref == ""
