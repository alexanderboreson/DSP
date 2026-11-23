"""Förstärkning med linjär rampning, så att nivåändringar inte klickar."""

from __future__ import annotations

import numpy as np


class SmoothedGain:
    def __init__(self, fs: float, initial: float = 1.0, ramp_ms: float = 20.0) -> None:
        self.fs = float(fs)
        self.default_ramp_ms = float(ramp_ms)
        self._cur = float(initial)
        self._tgt = float(initial)
        self._step = 0.0

    @property
    def current(self) -> float:
        return self._cur

    @property
    def target(self) -> float:
        return self._tgt

    @property
    def is_closed(self) -> bool:
        """Helt tyst och på väg att förbli tyst."""
        return self._cur == 0.0 and self._tgt == 0.0

    def set_immediate(self, value: float) -> None:
        self._cur = self._tgt = float(value)
        self._step = 0.0

    def set_target(self, value: float, ramp_ms: float | None = None) -> None:
        value = float(value)
        if value == self._tgt:
            return
        ms = self.default_ramp_ms if ramp_ms is None else ramp_ms
        ramp_samples = max(1, int(ms * self.fs / 1000.0))
        self._tgt = value
        self._step = (value - self._cur) / ramp_samples

    def advance(self, n: int) -> None:
        """Flyttar fram rampen utan att bearbeta ljud."""
        if self._cur == self._tgt:
            return
        self._cur = self._clamped(self._cur + self._step * n)

    def _clamped(self, v: float) -> float:
        return min(v, self._tgt) if self._step > 0 else max(v, self._tgt)

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        if self._cur == self._tgt:
            return (x * np.float32(self._cur)).astype(np.float32, copy=False)
        ramp = self._cur + self._step * np.arange(1, n + 1)
        if self._step > 0:
            np.minimum(ramp, self._tgt, out=ramp)
        else:
            np.maximum(ramp, self._tgt, out=ramp)
        self._cur = float(ramp[-1])
        return (x * ramp[:, None].astype(np.float32)).astype(np.float32, copy=False)
