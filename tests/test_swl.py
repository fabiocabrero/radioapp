from datetime import date, datetime, timezone

from ic7300 import swl

SAMPLE = """kHz:75;Time(UTC):93;Days:59;ITU:49;Station:201;Lng:49;Target:62;Remarks:135;P:35;Start:60;Stop:60;
5985;2200-2300;;HOL;Radio Netherlands;S;SAm;;100;;
9580;2330-0030;;B;Radio Nacional;P;LAm;;250;;
6070;1000-1100;Sa,Su;D;Deutsche Station;G;Eu;;50;;
7200;0600-0700;Mo-Fr;E;Radio Exterior;S;Am;;100;;
11800;0000-2400;irr;USA;Irregular Test;E;NAm;;10;;
15000;0900-1000;;CLA;Clandestine;K;Glo;;10;0110;2410
3000;1200-1230;5Apr;J;One Day;J;FE;;10;;
"""


def utc(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def entries():
    return {int(e.freq_khz): e for e in swl.parse_schedule(SAMPLE)}


def test_parse():
    e = entries()
    assert len(e) == 7 and e[5985].station == "Radio Netherlands" and e[5985].power == 100
    assert e[9580].start_min == 23 * 60 + 30 and e[9580].end_min == 30


def test_on_air_window_and_midnight_wrap():
    e = entries()
    assert swl.on_air(e[5985], utc(2026, 10, 31, 22, 30)) is True
    assert swl.on_air(e[5985], utc(2026, 10, 31, 23, 0)) is False
    assert swl.on_air(e[9580], utc(2026, 11, 1, 0, 10)) is True      # depois da meia-noite
    assert swl.on_air(e[9580], utc(2026, 10, 31, 23, 45)) is True
    assert swl.minutes_left(e[9580], utc(2026, 10, 31, 23, 45)) == 45


def test_days_rules():
    e = entries()
    assert swl.on_air(e[6070], utc(2026, 10, 31, 10, 30)) is True    # sábado
    assert swl.on_air(e[6070], utc(2026, 11, 2, 10, 30)) is False    # segunda
    assert swl.on_air(e[7200], utc(2026, 11, 2, 6, 30)) is True      # Mo-Fr, segunda
    assert swl.on_air(e[7200], utc(2026, 10, 31, 6, 30)) is False    # sábado
    assert swl.on_air(e[11800], utc(2026, 10, 31, 12, 0)) is None    # irregular: talvez
    assert swl.on_air(e[3000], utc(2026, 4, 5, 12, 10)) is True      # data específica
    assert swl.on_air(e[3000], utc(2026, 4, 6, 12, 10)) is False


def test_date_range():
    e = entries()
    assert swl.on_air(e[15000], utc(2026, 10, 15, 9, 30)) is True
    assert swl.on_air(e[15000], utc(2026, 10, 30, 9, 30)) is False   # depois de 24/10
    assert swl.on_air(e[15000], utc(2026, 9, 15, 9, 30)) is False


def test_targets_from_brazil():
    lat, lon = -23.3, -47.3  # Itu
    assert swl.target_covers("SAm", lat, lon) is True
    assert swl.target_covers("LAm", lat, lon) is True
    assert swl.target_covers("B", lat, lon) is True
    assert swl.target_covers("Eu", lat, lon) is False
    assert swl.target_covers("Glo", lat, lon) is True
    assert swl.target_covers("Oc", lat, lon) is False
    assert swl.target_covers("XYZ", lat, lon) is None
    assert swl.target_covers("Oc", -35, 175) is True                 # atravessa o antimeridiano


def test_seasons_and_band_group():
    assert swl.seasons(date(2026, 10, 31)) == ("b26", "a26")
    assert swl.seasons(date(2026, 7, 1)) == ("a26", "b25")
    assert swl.seasons(date(2026, 2, 1)) == ("b25", "a25")
    assert swl.band_group(5985) == "80m-40m" and swl.band_group(9580) == "30m-20m"
    assert swl.band_group(17800) == "17m-15m"


def test_validate_rejects_garbage():
    import pytest

    with pytest.raises(ValueError):
        swl.validate("<html>erro</html>")
    with pytest.raises(ValueError):
        swl.validate(SAMPLE)  # cabeçalho certo, estações de menos
