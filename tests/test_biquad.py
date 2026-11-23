import numpy as np
import pytest
from scipy.signal import sos2zpk

from autodsp.dsp.biquad import bands_to_sos, design_band
from autodsp.dsp.params import ChainSettings, EQBand, validate_for_sample_rate
from autodsp.dsp.response import eq_response_db, predicted_peak_gain_db

FS = 48000


@pytest.mark.parametrize("gain", [-12.0, -3.0, 6.0, 15.0])
@pytest.mark.parametrize("f0", [100.0, 1000.0, 8000.0])
def test_peak_gain_at_center_frequency_matches_setting(gain, f0):
    band = EQBand(kind="peak", freq_hz=f0, gain_db=gain, q=1.4)
    resp = eq_response_db([band], FS, np.array([f0]))
    assert resp[0] == pytest.approx(gain, abs=0.01)


def test_low_shelf_asymptotes():
    band = EQBand(kind="low_shelf", freq_hz=1000, gain_db=6.0, q=0.707)
    resp = eq_response_db([band], FS, np.array([10.0, 20000.0]))
    assert resp[0] == pytest.approx(6.0, abs=0.2)
    assert resp[1] == pytest.approx(0.0, abs=0.2)


def test_high_shelf_asymptotes():
    band = EQBand(kind="high_shelf", freq_hz=2000, gain_db=-6.0, q=0.707)
    resp = eq_response_db([band], FS, np.array([20.0, 15000.0]))
    assert resp[0] == pytest.approx(0.0, abs=0.2)
    assert resp[1] == pytest.approx(-6.0, abs=0.6)


def test_disabled_band_is_identity():
    band = EQBand(kind="peak", freq_hz=1000, gain_db=12.0, enabled=False)
    sos = design_band(band, FS)
    assert np.allclose(sos, [1, 0, 0, 1, 0, 0])


@pytest.mark.parametrize("fs", [44100, 48000, 96000])
@pytest.mark.parametrize("kind", ["peak", "low_shelf", "high_shelf"])
def test_all_filters_stable_over_parameter_grid(fs, kind):
    for f in (20.0, 63.0, 500.0, 4000.0, 0.45 * fs if 0.45 * fs <= 20000 else 18000.0):
        for g in (-24.0, 0.0, 24.0):
            for q in (0.1, 0.707, 5.0, 20.0):
                sos = design_band(EQBand(kind=kind, freq_hz=f, gain_db=g, q=q), fs)
                _, poles, _ = sos2zpk(sos.reshape(1, 6))
                assert np.all(np.abs(poles) < 1.0), (kind, f, g, q)


def test_default_bands_are_ten_and_flat():
    s = ChainSettings()
    assert len(s.eq_bands) >= 10
    resp = eq_response_db(s.eq_bands, FS, np.geomspace(20, 20000, 100))
    assert np.max(np.abs(resp)) < 1e-6


def test_predicted_gain_includes_eq_boost_and_bypass():
    s = ChainSettings().replace(master_gain_db=0.0)
    s = s.with_band(4, EQBand(kind="peak", freq_hz=1000, gain_db=9.0, q=2.0))
    assert predicted_peak_gain_db(s, FS) == pytest.approx(9.0, abs=0.1)
    assert predicted_peak_gain_db(s.replace(eq_bypass=True), FS) == pytest.approx(0.0, abs=1e-9)


def test_band_too_close_to_nyquist_rejected():
    s = ChainSettings().with_band(5, EQBand(freq_hz=20000))
    with pytest.raises(ValueError):
        validate_for_sample_rate(s, 44100)
    validate_for_sample_rate(s, 96000)


def test_invalid_values_rejected_by_model():
    for bad in (float("nan"), float("inf"), -1.0, 1e9):
        with pytest.raises(ValueError):
            EQBand(freq_hz=bad)
    with pytest.raises(ValueError):
        EQBand(gain_db=float("nan"))
    with pytest.raises(ValueError):
        EQBand(q=0.0)
