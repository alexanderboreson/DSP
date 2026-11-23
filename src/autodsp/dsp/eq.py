"""Parametrisk EQ som en kaskad av biquad-sektioner med bibehållet filtertillstånd.

Ändrade koefficienter tonas över med en crossfade mellan gammalt och nytt filter
under ett block, och bypass tonas på samma sätt. Det undviker klick vid ändring.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from scipy.signal import sosfilt

from .biquad import bands_to_sos
from .params import EQBand


class ParametricEQ:
    def __init__(
        self, fs: float, channels: int, bands: Sequence[EQBand], bypass: bool = False
    ) -> None:
        self.fs = float(fs)
        self.channels = int(channels)
        self._sos = bands_to_sos(bands, self.fs)
        self._zi = np.zeros((self._sos.shape[0], 2, self.channels))
        self._pending: np.ndarray | None = None
        self._bypass_target = bool(bypass)
        self._mix = 1.0 if bypass else 0.0  # 1.0 = helt torr signal
        self.fault_count = 0

    # Anropas från ljudtråden vid blockgräns.
    def set_bands(self, bands: Sequence[EQBand]) -> None:
        sos = bands_to_sos(bands, self.fs)
        if self._pending is None and sos.shape == self._sos.shape and np.array_equal(sos, self._sos):
            return
        self._pending = sos

    def set_bypass(self, bypass: bool) -> None:
        self._bypass_target = bool(bypass)

    def reset(self) -> None:
        self._zi = np.zeros((self._sos.shape[0], 2, self.channels))

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        x64 = x.astype(np.float64, copy=False)
        wet, zi = sosfilt(self._sos, x64, axis=0, zi=self._zi)

        if self._pending is not None:
            new_sos = self._pending
            if new_sos.shape == self._sos.shape:
                zi_new = self._zi.copy()
            else:
                zi_new = np.zeros((new_sos.shape[0], 2, self.channels))
            wet_new, zi_new = sosfilt(new_sos, x64, axis=0, zi=zi_new)
            fade = (np.arange(1, n + 1) / n)[:, None]
            wet = wet * (1.0 - fade) + wet_new * fade
            self._sos = new_sos
            zi = zi_new
            self._pending = None
        self._zi = zi

        target = 1.0 if self._bypass_target else 0.0
        if self._mix != target:
            ramp = (self._mix + (target - self._mix) * np.arange(1, n + 1) / n)[:, None]
            y = x64 * ramp + wet * (1.0 - ramp)
            self._mix = target
        else:
            y = x64 if target == 1.0 else wet

        if not np.isfinite(y).all():
            self.fault_count += 1
            self.reset()
            return np.zeros_like(x, dtype=np.float32)
        return y.astype(np.float32)
