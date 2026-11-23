"""Lookahead-peaklimiter med exponentiell release.

Princip (blockbaserad, med tillstånd mellan block):
 1. Per sampel beräknas erforderlig förstärkning så att toppen hamnar under taket.
 2. Ett glidande minimum över lookahead-fönstret gör att reduktionen börjar i tid.
 3. Release: reduktionen återhämtar sig exponentiellt mot 1.0 (nedåt direkt).
 4. Ett glidande medelvärde över lookahead-längden ger mjuk attack. Eftersom varje
    värde i medelvärdet är <= kravet för det aktuella sampeln kan medelvärdet aldrig
    överskrida taket. En sista hård klippning tar hand om flyttalsavrundning.

Ljudet fördröjs lookahead sampel (se `lookahead`). Limitern är en digital
nivåbegränsare; den skyddar inte hårdvara mot t.ex. för hög förstärkargain.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .units import db_to_lin, lin_to_db


class PeakLimiter:
    def __init__(
        self,
        fs: float,
        channels: int,
        threshold_db: float = -1.0,
        lookahead_ms: float = 1.5,
        release_ms: float = 100.0,
    ) -> None:
        if channels < 1:
            raise ValueError("channels måste vara >= 1")
        self.fs = float(fs)
        self.channels = int(channels)
        self.lookahead = max(1, int(round(lookahead_ms * self.fs / 1000.0)))
        self._ceiling = db_to_lin(threshold_db)
        self._release_frac = self._frac(release_ms)
        self._kernel = np.full(self.lookahead + 1, 1.0 / (self.lookahead + 1))
        self.gain_reduction_db = 0.0
        self.reset()

    def _frac(self, release_ms: float) -> float:
        return 1.0 - math.exp(-1.0 / max(1.0, release_ms * self.fs / 1000.0))

    def set_params(self, threshold_db: float, release_ms: float) -> None:
        self._ceiling = db_to_lin(threshold_db)
        self._release_frac = self._frac(release_ms)

    def reset(self) -> None:
        L = self.lookahead
        self._audio = np.zeros((L, self.channels), dtype=np.float32)
        self._req = np.ones(L)
        self._env_hist = np.ones(L)
        self._env = 1.0
        self.gain_reduction_db = 0.0

    def _release(self, gmin: np.ndarray) -> np.ndarray:
        e = self._env
        if e >= 1.0 and float(gmin.min()) >= 1.0:
            return gmin  # snabbväg: ingen reduktion pågår
        frac = self._release_frac
        out = np.empty(gmin.shape[0])
        for i, g in enumerate(gmin.tolist()):
            rec = e + (1.0 - e) * frac
            e = g if g < rec else rec
            if e > 0.999999999:
                e = 1.0
            out[i] = e
        self._env = e
        return out

    def process(self, x: np.ndarray) -> np.ndarray:
        n = x.shape[0]
        if n == 0:
            return x
        L = self.lookahead
        ceiling = self._ceiling

        peak = np.max(np.abs(x), axis=1).astype(np.float64)
        req = np.ones(n)
        over = peak > ceiling
        if over.any():
            req[over] = ceiling / peak[over]

        audio_all = np.concatenate((self._audio, x.astype(np.float32, copy=False)), axis=0)
        req_all = np.concatenate((self._req, req))

        gmin = sliding_window_view(req_all, L + 1).min(axis=1)  # längd n
        env = self._release(gmin)
        env_all = np.concatenate((self._env_hist, env))
        gain = np.convolve(env_all, self._kernel, mode="valid")  # längd n

        out = audio_all[:n] * gain[:, None].astype(np.float32)
        np.clip(out, -ceiling, ceiling, out=out)

        self._audio = audio_all[-L:].copy()
        self._req = req_all[-L:].copy()
        self._env_hist = env_all[-L:].copy()
        self.gain_reduction_db = max(0.0, -lin_to_db(float(gain.min())))
        return out
