"""Biquad-design enligt RBJ Audio EQ Cookbook, levererat som SOS-rader.

Varje rad är [b0, b1, b2, 1, a1, a2] (normaliserad med a0), kompatibel med
scipy.signal.sosfilt / sosfreqz.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from .params import EQBand

IDENTITY_SECTION = np.array([1.0, 0.0, 0.0, 1.0, 0.0, 0.0])


def design_band(band: EQBand, fs: float) -> np.ndarray:
    """Beräknar en SOS-rad för ett EQ-band. Avaktiverade band blir identitet."""
    if not band.enabled:
        return IDENTITY_SECTION.copy()

    amp = 10.0 ** (band.gain_db / 40.0)
    w0 = 2.0 * math.pi * band.freq_hz / fs
    cosw = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * band.q)

    if band.kind == "peak":
        b0 = 1.0 + alpha * amp
        b1 = -2.0 * cosw
        b2 = 1.0 - alpha * amp
        a0 = 1.0 + alpha / amp
        a1 = -2.0 * cosw
        a2 = 1.0 - alpha / amp
    elif band.kind == "low_shelf":
        sq = 2.0 * math.sqrt(amp) * alpha
        b0 = amp * ((amp + 1) - (amp - 1) * cosw + sq)
        b1 = 2.0 * amp * ((amp - 1) - (amp + 1) * cosw)
        b2 = amp * ((amp + 1) - (amp - 1) * cosw - sq)
        a0 = (amp + 1) + (amp - 1) * cosw + sq
        a1 = -2.0 * ((amp - 1) + (amp + 1) * cosw)
        a2 = (amp + 1) + (amp - 1) * cosw - sq
    elif band.kind == "high_shelf":
        sq = 2.0 * math.sqrt(amp) * alpha
        b0 = amp * ((amp + 1) + (amp - 1) * cosw + sq)
        b1 = -2.0 * amp * ((amp - 1) + (amp + 1) * cosw)
        b2 = amp * ((amp + 1) + (amp - 1) * cosw - sq)
        a0 = (amp + 1) - (amp - 1) * cosw + sq
        a1 = 2.0 * ((amp - 1) - (amp + 1) * cosw)
        a2 = (amp + 1) - (amp - 1) * cosw - sq
    else:  # pragma: no cover - skyddas av pydantic
        raise ValueError(f"Okänd bandtyp: {band.kind}")

    return np.array([b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0])


def bands_to_sos(bands: Iterable[EQBand], fs: float) -> np.ndarray:
    rows = [design_band(b, fs) for b in bands]
    return np.vstack(rows) if rows else IDENTITY_SECTION.reshape(1, 6).copy()
