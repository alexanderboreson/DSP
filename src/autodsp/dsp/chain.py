"""Signalkedja:

Input -> Input Meter -> Input Gain -> EQ -> Master Gain (inkl. mute) -> Limiter -> Output
"""

from __future__ import annotations

import numpy as np

from .eq import ParametricEQ
from .gain import SmoothedGain
from .limiter import PeakLimiter
from .meters import measure
from .params import ChainSettings, validate_for_sample_rate
from .units import db_to_lin


class ProcessingChain:
    def __init__(self, fs: float, channels: int, settings: ChainSettings) -> None:
        validate_for_sample_rate(settings, fs)
        self.fs = float(fs)
        self.channels = int(channels)
        self.input_gain = SmoothedGain(fs, db_to_lin(settings.input_gain_db))
        self.eq = ParametricEQ(fs, channels, settings.eq_bands, settings.eq_bypass)
        self.master = SmoothedGain(fs, self._master_target(settings))
        self.limiter = PeakLimiter(
            fs,
            channels,
            threshold_db=settings.limiter_threshold_db,
            release_ms=settings.limiter_release_ms,
        )
        self.last_input_peak_db: tuple[float, ...] = (-120.0,) * channels
        self.last_input_rms_db: tuple[float, ...] = (-120.0,) * channels
        self.last_input_clipped = False
        self.sanitized_blocks = 0

    @property
    def latency_samples(self) -> int:
        return self.limiter.lookahead

    @staticmethod
    def _master_target(settings: ChainSettings) -> float:
        return 0.0 if settings.mute else db_to_lin(settings.master_gain_db)

    def apply(self, settings: ChainSettings) -> None:
        validate_for_sample_rate(settings, self.fs)
        self.input_gain.set_target(db_to_lin(settings.input_gain_db))
        self.eq.set_bands(settings.eq_bands)
        self.eq.set_bypass(settings.eq_bypass)
        self.master.set_target(self._master_target(settings))
        self.limiter.set_params(settings.limiter_threshold_db, settings.limiter_release_ms)

    def reset(self) -> None:
        self.eq.reset()
        self.limiter.reset()

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        if not np.isfinite(x).all():
            self.sanitized_blocks += 1
            x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        self.last_input_peak_db, self.last_input_rms_db, self.last_input_clipped = measure(x)
        y = self.input_gain.process(x)
        y = self.eq.process(y)
        y = self.master.process(y)
        return self.limiter.process(y)

    @property
    def gain_reduction_db(self) -> float:
        return self.limiter.gain_reduction_db
