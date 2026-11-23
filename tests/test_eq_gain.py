import numpy as np
import pytest

from autodsp.dsp.eq import ParametricEQ
from autodsp.dsp.gain import SmoothedGain
from autodsp.dsp.params import ChainSettings, EQBand
from helpers import sine

FS = 48000


def _eq(bands=None, channels=2):
    return ParametricEQ(FS, channels, bands or ChainSettings().eq_bands)


def test_block_processing_matches_one_shot_filtering():
    bands = ChainSettings().eq_bands[:3] + (EQBand(kind="peak", freq_hz=1000, gain_db=8, q=2),)
    x = np.random.default_rng(1).standard_normal((4800, 2)).astype(np.float32) * 0.2
    whole = ParametricEQ(FS, 2, bands).process(x)
    eq = ParametricEQ(FS, 2, bands)
    blocks = np.concatenate([eq.process(x[i : i + 333]) for i in range(0, 4800, 333)])
    assert np.allclose(whole, blocks, atol=1e-6)


def test_sine_level_change_matches_filter_gain():
    bands = (EQBand(kind="peak", freq_hz=1000, gain_db=6.0, q=1.0),)
    eq = ParametricEQ(FS, 2, bands)
    x = sine(1000, FS, 1.0, 0.1)
    y = eq.process(x)
    ratio = np.sqrt(np.mean(y[-9600:] ** 2)) / np.sqrt(np.mean(x[-9600:] ** 2))
    assert 20 * np.log10(ratio) == pytest.approx(6.0, abs=0.1)


def test_coefficient_change_mid_stream_has_no_discontinuity():
    eq = ParametricEQ(FS, 2, (EQBand(kind="peak", freq_hz=1000, gain_db=0.0, q=1.0),))
    x = sine(1000, FS, 1.0, 0.5)
    y1 = eq.process(x[:24000])
    eq.set_bands((EQBand(kind="peak", freq_hz=1000, gain_db=12.0, q=1.0),))
    y2 = eq.process(x[24000:24512])
    y3 = eq.process(x[24512:])
    y = np.concatenate([y1, y2, y3])
    max_step = np.max(np.abs(np.diff(y[:, 0])))
    # sinus 0.5 vid 1 kHz har max steg ~0.065; med +12 dB (x4) kan upp till ~0.26 uppstå
    assert max_step < 0.3
    # jämför mot ett hårt byte utan crossfade: ska inte vara värre än kontinuerlig sinus*gain
    assert np.isfinite(y).all()


def test_bypass_toggle_is_smooth():
    bands = (EQBand(kind="peak", freq_hz=1000, gain_db=12.0, q=1.0),)
    eq = ParametricEQ(FS, 2, bands)
    x = sine(1000, FS, 0.5, 0.2)
    y1 = eq.process(x[:12000])
    eq.set_bypass(True)
    y2 = eq.process(x[12000:])
    y = np.concatenate([y1, y2])
    assert np.max(np.abs(np.diff(y[:, 0]))) < 0.2


def test_eq_handles_band_count_change():
    eq = ParametricEQ(FS, 2, ChainSettings().eq_bands)
    x = sine(500, FS, 0.2)
    eq.process(x)
    eq.set_bands(ChainSettings().eq_bands[:4])
    y = eq.process(x)
    assert np.isfinite(y).all()


def test_eq_recovers_from_nonfinite_output():
    eq = _eq()
    x = np.full((256, 2), np.float32("inf"))
    y = eq.process(x)
    assert np.all(y == 0)
    assert eq.fault_count == 1
    assert np.isfinite(eq.process(sine(1000, FS, 0.05))).all()


def test_gain_ramps_linearly_and_reaches_target():
    g = SmoothedGain(FS, initial=1.0, ramp_ms=10.0)
    g.set_target(0.0)
    y = g.process(np.ones((960, 2), dtype=np.float32))  # 20 ms
    ramp = y[:, 0]
    assert ramp[0] > 0.99  # ingen hård stegändring
    assert np.all(np.diff(ramp) <= 1e-7)
    assert ramp[480:].max() == 0.0
    assert g.is_closed


def test_gain_ramp_spans_multiple_blocks():
    g = SmoothedGain(FS, initial=0.0, ramp_ms=20.0)  # 960 sampel
    g.set_target(1.0)
    out = np.concatenate([g.process(np.ones((100, 1), dtype=np.float32)) for _ in range(12)])
    assert out[0, 0] < 0.01
    assert np.all(np.diff(out[:, 0]) >= -1e-7)
    assert out[-1, 0] == 1.0
    assert np.max(np.diff(out[:, 0])) < 0.0012


def test_gain_advance_matches_process():
    a = SmoothedGain(FS, 1.0, 5.0)
    b = SmoothedGain(FS, 1.0, 5.0)
    a.set_target(0.0)
    b.set_target(0.0)
    a.process(np.ones((100, 2), dtype=np.float32))
    b.advance(100)
    assert a.current == pytest.approx(b.current)
