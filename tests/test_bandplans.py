import json
from pathlib import Path

import pytest

from ic7300.bands import BandPlan, choose_plan, iaru_region
from ic7300.dxcc import Cty

DATA = Path(__file__).parent.parent / "ic7300" / "data"


@pytest.fixture(scope="module")
def cty():
    return Cty()


@pytest.fixture()
def br(tmp_path):
    return BandPlan("BR", custom_path=tmp_path / "nenhum.json")


def test_plan_selection_by_callsign_and_position(cty):
    assert choose_plan("PY2XX", 0, 0, cty) == "BR"
    assert choose_plan("PU2ABC", 0, 0, cty) == "BR"
    assert choose_plan("W1AW", 0, 0, cty) == "IARU-R2"
    assert choose_plan("G3ABC", 0, 0, cty) == "IARU-R1"
    assert choose_plan("JA1ABC", 0, 0, cty) == "IARU-R3"
    assert choose_plan("ZS6XYZ", 0, 0, cty) == "IARU-R1"
    assert choose_plan("UA9XYZ", 0, 0, cty) == "IARU-R1"      # Rússia asiática é Região 1
    assert choose_plan("KH6ABC", 0, 0, cty) == "IARU-R2"      # Havaí é Região 2
    assert choose_plan("", -23.26, -47.30, cty) == "BR"       # sem indicativo, pela posição (Itu)
    assert choose_plan("", 51.5, -0.1, cty) == "IARU-R1"      # Londres
    assert choose_plan("", 0, 0, None) == "IARU-R2"
    assert iaru_region("Japan", "AS") == 3


def test_brazil_plan_classes_power_and_edges(br):
    assert br.max_power("A") == 1500 and br.max_power("B") == 1000 and br.max_power("C") == 100
    assert br.band_range("40m") == (7_000_000, 7_300_000)
    assert br.band_range("80m") == (3_500_000, 4_000_000)
    assert br.segment_for(7_030_000).classes == "ABC"
    assert br.segment_for(7_074_000).classes == "AB"          # 40 m acima de 7047 kHz: classes A e B
    assert br.segment_for(14_074_000).classes == "A"          # 20 m: só classe A
    assert br.segment_for(5_357_000).classes == "A" and "25 W" in br.segment_for(5_357_000).note
    assert br.segment_for(3_850_000).classes == "A" and br.segment_for(3_700_000).classes == "ABC"
    assert br.segment_for(21_250_000).classes == "AB" and br.segment_for(21_400_000).classes == "A"
    assert br.segment_for(14_100_000).use == "BCN"
    assert br.segment_for(29_540_000).use == "REP"
    assert br.suggest_mode(14_074_000) == ("USB", True)
    assert br.suggest_mode(7_030_000) == ("CW", False)
    assert br.suggest_mode(7_150_000) == ("LSB", False)


def test_tx_status_warnings(br):
    assert br.tx_status(7_030_000, "C", "CW").ok
    assert br.tx_status(7_030_000, "C", "DIG").level == "mode"          # 7000-7040: só CW
    assert br.tx_status(7_074_000, "C", "DIG").level == "class"         # classe C não tem 7047+
    assert br.tx_status(7_074_000, "B", "DIG").ok
    assert br.tx_status(7_074_000, "", "DIG").ok                        # classe não informada: não avalia classe
    assert br.tx_status(14_074_000, "B", "DIG").level == "class"
    assert br.tx_status(14_074_000, "A", "DIG").ok
    assert br.tx_status(14_100_000, "A", "SSB").level == "beacon"
    assert br.tx_status(29_540_000, "A", "SSB").level == "repeater"
    out = br.tx_status(9_000_000, "A", "SSB")
    assert out.level == "outside" and "Brasil" in out.text
    assert br.category("USB", data=True) == "DIG" and br.category("LSB") == "SSB" and br.category("CW-R") == "CW"
    assert br.category("RTTY") == "DIG" and br.category("AM") == "AM"


def test_every_standard_ft8_ft4_frequency_is_a_digital_segment_in_brazil(br):
    """Valida a extração do plano contra frequências de FT8/FT4 que são legais no Brasil."""
    dig = json.loads((DATA / "digital_modes.json").read_text(encoding="utf-8"))
    for d in dig:
        if d["type"] not in ("FT8", "FT4"):
            continue
        seg = br.segment_for(d["freq"])
        assert seg is not None, d["label"]
        assert "DIG" in seg.modes, (d["label"], seg)
        top = br.segment_for(d["freq"] + 2500)
        assert top is not None and "DIG" in top.modes, (d["label"], top)


def test_generic_regional_plans_follow_itu_allocations(tmp_path):
    r1, r2, r3 = (BandPlan(p, custom_path=tmp_path / "x.json") for p in ("IARU-R1", "IARU-R2", "IARU-R3"))
    assert r1.band_range("40m")[1] == 7_200_000 and r2.band_range("40m")[1] == 7_300_000 and r3.band_range("40m")[1] == 7_200_000
    assert r1.band_range("80m")[1] == 3_800_000 and r2.band_range("80m")[1] == 4_000_000 and r3.band_range("80m")[1] == 3_900_000
    assert r1.band_range("160m")[0] == 1_810_000 and r2.band_range("160m")[0] == 1_800_000
    assert r1.generic and r1.tx_status(7_100_000, "C", "SSB").ok          # genérico: sem classes nem modos detalhados
    assert r1.tx_status(7_250_000, "", "SSB").level == "outside"          # 7200+ não é radioamador na Região 1
    assert r2.tx_status(7_250_000, "", "SSB").ok


def test_custom_plan_file_adds_and_overrides_plans(tmp_path):
    custom = tmp_path / "bandplans_custom.json"
    custom.write_text(json.dumps({"plans": {"XX": {"name": "País de teste", "region": 1, "generic": True, "bands": [
        {"name": "20m", "start": 14_000_000, "stop": 14_350_000, "segments": [
            {"start": 14_000_000, "stop": 14_350_000, "use": "ALL", "modes": [], "classes": ""}]}]}}}), encoding="utf-8")
    plan = BandPlan("XX", custom_path=custom)
    assert plan.name == "País de teste" and plan.band_names() == ["20m"]
    assert ("BR", "Brasil (Anatel, Ato 926/2024)") in plan.available()
    assert BandPlan("naoexiste", custom_path=custom).plan_id == "IARU-R2"
