"""Beräknad frekvensrespons (matematisk modell, INTE en mätning)."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from scipy.signal import sosfreqz

from .biquad import bands_to_sos
from .params import EQBand, ChainSettings


def log_freq_grid(n: int = 512, f_min: float = 20.0, f_max: float = 20_000.0) -> np.ndarray:
    return np.geomspace(f_min, f_max, n)


def sos_response_db(sos: np.ndarray, freqs: np.ndarray, fs: float) -> np.ndarray:
    _, h = sosfreqz(sos, worN=freqs, fs=fs)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def eq_response_db(bands: Sequence[EQBand], fs: float, freqs: np.ndarray) -> np.ndarray:
    return sos_response_db(bands_to_sos(bands, fs), freqs, fs)


def predicted_peak_gain_db(settings: ChainSettings, fs: float) -> float:
    """Värsta tänkbara digitala förstärkning (dB) vid någon frekvens.

    input_gain + EQ-responsens maximum + master. Detta är en beräkning, inte
    en mätning, och säger inget om akustisk eller elektrisk nivå.
    """
    peak_eq = 0.0
    if not settings.eq_bypass:
        peak_eq = float(np.max(eq_response_db(settings.eq_bands, fs, log_freq_grid(256))))
    return float(settings.input_gain_db + peak_eq + settings.master_gain_db)
