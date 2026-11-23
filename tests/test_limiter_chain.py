import numpy as np
import pytest

from autodsp.dsp.chain import ProcessingChain
from autodsp.dsp.limiter import PeakLimiter
from autodsp.dsp.units import db_to_lin
from helpers import flat_settings, sine


@pytest.mark.parametrize("fs", [44100, 48000, 96000])
@pytest.mark.parametrize("block", [64, 512, 1000])
def test_limiter_never_exceeds_ceiling(fs, block):
    lim = PeakLimiter(fs, 2, threshold_db=-3.0, release_ms=50.0)
    ceiling = db_to_lin(-3.0)
    rng = np.random.default_rng(0)
    x = sine(440, fs, 1.0, amp=4.0)
    x[1000, :] = 20.0  # transient
    x[5000, 0] = -30.0
    x += rng.standard_normal(x.shape).astype(np.float32) * 0.3
    out = np.concatenate([lim.process(x[i : i + block]) for i in range(0, len(x), block)])
    assert np.max(np.abs(out)) <= ceiling + 1e-6


def test_limiter_is_transparent_below_threshold():
    lim = PeakLimiter(48000, 2, threshold_db=-1.0)
    x = sine(1000, 48000, 0.5, amp=0.3)
    out = lim.process(x)
    L = lim.lookahead
    assert np.allclose(out[L:], x[:-L], atol=1e-6)
    assert lim.gain_reduction_db == 0.0


def test_limiter_reports_reduction_and_recovers():
    fs = 48000
    lim = PeakLimiter(fs, 2, threshold_db=-6.0, release_ms=50.0)
    loud = sine(200, fs, 0.2, amp=1.0)
    lim.process(loud)
    assert lim.gain_reduction_db > 3.0
    quiet = sine(200, fs, 1.0, amp=0.1)
    out = lim.process(quiet)
    tail = out[-4800:]
    ratio = np.max(np.abs(tail)) / 0.1
    assert ratio > 0.99  # återhämtad efter 5 releasetider


def test_limiter_state_continuity_across_block_sizes():
    fs = 48000
    x = sine(300, fs, 0.5, amp=2.0)
    a = PeakLimiter(fs, 2, -2.0, release_ms=80.0)
    b = PeakLimiter(fs, 2, -2.0, release_ms=80.0)
    whole = a.process(x)
    parts = np.concatenate([b.process(x[i : i + 480]) for i in range(0, len(x), 480)])
    assert np.allclose(whole, parts, atol=1e-5)


def test_chain_unity_passthrough_with_latency():
    fs = 48000
    chain = ProcessingChain(fs, 2, flat_settings(limiter_threshold_db=-0.1))
    x = sine(1000, fs, 0.5, 0.5)
    y = chain.process(x)
    L = chain.latency_samples
    assert np.allclose(y[L:], x[:-L], atol=1e-5)


def test_chain_master_gain_applied():
    fs = 48000
    chain = ProcessingChain(fs, 2, flat_settings(master_gain_db=-6.0))
    x = sine(1000, fs, 0.5, 0.5)
    y = chain.process(x)
    L = chain.latency_samples
    assert np.max(np.abs(y[L:])) == pytest.approx(0.5 * db_to_lin(-6.0), rel=0.01)


def test_chain_mute_ramps_to_silence_without_step():
    fs = 48000
    chain = ProcessingChain(fs, 2, flat_settings())
    x = sine(1000, fs, 1.0, 0.5)
    y1 = chain.process(x[:24000])
    chain.apply(flat_settings(mute=True))
    y2 = chain.process(x[24000:])
    y = np.concatenate([y1, y2])
    assert np.max(np.abs(y[-2000:])) == 0.0
    assert np.max(np.abs(np.diff(y[:, 0]))) < 0.1


def test_chain_survives_nan_and_inf_input():
    fs = 48000
    chain = ProcessingChain(fs, 2, flat_settings())
    x = sine(1000, fs, 0.1)
    x[100, 0] = np.nan
    x[200, 1] = np.inf
    x[300, 0] = -np.inf
    y = chain.process(x)
    assert np.isfinite(y).all()
    assert chain.sanitized_blocks == 1
    assert np.isfinite(chain.process(sine(1000, fs, 0.1))).all()


@pytest.mark.parametrize("fs", [44100, 48000, 96000, 192000])
@pytest.mark.parametrize("channels", [1, 2, 6])
def test_chain_supports_rates_and_channel_counts(fs, channels):
    chain = ProcessingChain(fs, channels, flat_settings())
    x = sine(1000, fs, 0.1, 0.5, channels=channels)
    y = chain.process(x)
    assert y.shape == x.shape and np.isfinite(y).all()


def test_chain_settings_change_during_processing_stays_under_ceiling():
    fs = 48000
    s = flat_settings(limiter_threshold_db=-1.0)
    chain = ProcessingChain(fs, 2, s)
    ceiling = db_to_lin(-1.0)
    x = sine(300, fs, 0.05, amp=0.9)
    peak = 0.0
    for i in range(60):
        chain.apply(s.replace(master_gain_db=float((i % 7) * 3 - 12), input_gain_db=float(i % 5)))
        peak = max(peak, float(np.max(np.abs(chain.process(x)))))
    assert peak <= ceiling + 1e-6
