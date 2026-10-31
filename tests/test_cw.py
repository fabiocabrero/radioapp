import numpy as np

from ic7300.dsp.cw_decoder import CwDecoder, text_to_morse_audio


def decode(audio, **kw):
    dec = CwDecoder(**kw)
    out = ""
    for i in range(0, len(audio), 4800):
        out += dec.process(audio[i:i + 4800])
    out += dec.process(np.zeros(48000))
    return " ".join(out.split()), dec


def test_clean_20wpm():
    text = "CQ CQ DE PY2XX K"
    pad = np.zeros(72000)
    audio = np.concatenate([pad, text_to_morse_audio(text, 20, 600), pad])
    out, dec = decode(audio)
    assert out == text
    assert 17 < dec.wpm < 23


def test_noisy_other_pitch_and_speed():
    text = "TNX FER QSO 73"
    rng = np.random.default_rng(1)
    sig = text_to_morse_audio(text, 14, 750, amp=0.3)
    audio = np.concatenate([np.zeros(72000), sig, np.zeros(72000)])
    audio += rng.normal(0, 0.05, len(audio))
    out, dec = decode(audio)
    assert out == text
    assert 700 < dec.tone < 800


def test_silence_gives_nothing():
    rng = np.random.default_rng(2)
    out, _ = decode(rng.normal(0, 0.02, 96000))
    assert out == ""
