import numpy as np

from ic7300.dsp import rtty


def run(audio, chunk=2400, **kw):
    dec = rtty.RttyDecoder(**kw)
    out = ""
    for i in range(0, len(audio), chunk):
        out += dec.process(audio[i:i + chunk])
    return out


def test_baudot_roundtrip_codes():
    text = "CQ CQ DE PY2XX 599 +/-:?"
    codes = rtty.text_to_codes(text)
    assert rtty.decode_codes(codes) == text


def test_audio_roundtrip_clean():
    text = "CQ CQ DE PY2XX PY2XX K"
    audio = rtty.encode(text)
    assert run(audio).strip() == text


def test_figures_and_noise():
    text = "UR RST 599 599 NAME FABIO QTH ITU 2026"
    audio = rtty.encode(text, amp=0.3)
    audio = np.concatenate([np.zeros(24000), audio, np.zeros(24000)])
    audio = audio + np.random.default_rng(3).normal(0, 0.05, len(audio)).astype(np.float32)
    assert run(audio).strip() == text


def test_other_baud_reverse_and_odd_chunks():
    text = "TEST DE W1AW"
    audio = rtty.encode(text, baud=50.0, mark=1275.0, shift=170.0, reverse=True)
    out = run(audio, chunk=1777, baud=50.0, mark=1275.0, shift=170.0, reverse=True)
    assert out.strip() == text


def test_wrong_polarity_does_not_decode_text():
    audio = rtty.encode("CQ DE PY2XX K", reverse=True)
    assert run(audio, reverse=False).strip() != "CQ DE PY2XX K"


def test_silence_and_noise_give_nothing():
    rng = np.random.default_rng(5)
    assert run(rng.normal(0, 0.01, 96000)).strip() == ""


def test_without_unshift_on_space_both_ends():
    text = "RST 599 599 NAME FABIO"
    audio = rtty.encode(text, uos=False)
    assert run(audio, unshift_on_space=False).strip() == text
    # receptor com UOS lendo transmissão sem UOS erra as letras depois dos números: comportamento esperado
    assert run(audio, unshift_on_space=True).strip() != text
