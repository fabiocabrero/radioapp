import json
from pathlib import Path

import pytest

from ic7300 import extapps
from ic7300.bands import BandPlan

DATA = Path(__file__).parent.parent / "ic7300" / "data" / "protocols.json"


@pytest.fixture(scope="module")
def doc():
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_catalogue_is_consistent(doc):
    keys = [p["key"] for p in doc["protocols"]]
    assert len(keys) == len(set(keys)) >= 15
    for p in doc["protocols"]:
        assert p["app"] in ("native", "engine", "external", "none") and p["recognition"] and p["summary"]
        if p["app"] == "external":
            assert extapps.by_key(p["ext"])          # todo protocolo externo aponta para um programa do catálogo
        if p["app"] in ("native", "engine"):
            assert p["page"] in ("cw", "rtty", "ft8", "sstv", "wsjt")
    assert {"ft8", "rtty", "sstv", "winlink", "vara", "ardop", "psk31"} <= set(keys)


def test_activity_centers_match_the_iaru_r2_plan(doc):
    plan = BandPlan("IARU-R2", custom_path=Path(DATA).parent / "nenhum.json")
    for c in doc["centers"]:
        hz = int(c["khz"] * 1000)
        seg = plan.segment_for(hz)
        assert seg is not None, c                      # todo centro de atividade cai dentro de um segmento do plano
        if c["kind"] in ("Emergência", "Imagem (SSTV/FAX)", "Voz digital", "SSB QRP"):
            assert "SSB" in seg.modes or "DV" in seg.modes or seg.use == "ALL", (c, seg)
        if c["kind"].startswith("CW"):
            assert "CW" in seg.modes, (c, seg)


def test_tune_mode_choices():
    from ic7300.ui.protocolstab import tune_mode

    assert tune_mode("CW QRP", 14060) == ("CW", False)
    assert tune_mode("Imagem (SSTV/FAX)", 14230) == ("USB", True)
    assert tune_mode("Imagem (SSTV/FAX)", 7165) == ("LSB", True)
    assert tune_mode("Emergência", 3750) == ("LSB", False)
    assert tune_mode("AM", 14285) == ("AM", False) and tune_mode("FM chamada", 29600) == ("FM", False)
    assert tune_mode("6 m", 50305) == ("USB", True)
