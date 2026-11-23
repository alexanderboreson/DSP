"""FFT-spektrum av digital signal (dBFS). Detta är en signalanalys, inte en akustisk mätning."""

from __future__ import annotations

import numpy as np
from scipy.signal import get_window


def compute_spectrum_db(
    samples: np.ndarray, fs: float, n_fft: int = 4096
) -> tuple[np.ndarray, np.ndarray]:
    """Returnerar (frekvenser, nivå i dBFS). En fullskalig sinus vid en bin ger 0 dBFS."""
    x = np.asarray(samples, dtype=np.float64).ravel()
    if x.size >= n_fft:
        x = x[-n_fft:]
    else:
        x = np.concatenate((np.zeros(n_fft - x.size), x))
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    window = get_window("hann", n_fft)  # periodisk
    spec = np.abs(np.fft.rfft(x * window)) * 2.0 / np.sum(window)
    db = 20.0 * np.log10(np.maximum(spec, 1e-9))
    return np.fft.rfftfreq(n_fft, 1.0 / fs), db
