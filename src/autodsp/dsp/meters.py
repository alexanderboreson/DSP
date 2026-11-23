"""Digitala nivåmätare (dBFS). Mäter digital signalnivå, inte akustisk eller elektrisk."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .units import FLOOR_DB, lin_to_db

CLIP_THRESHOLD = 0.999


@dataclass(frozen=True)
class MeterSnapshot:
    in_peak_db: tuple[float, ...]
    in_rms_db: tuple[float, ...]
    out_peak_db: tuple[float, ...]
    out_rms_db: tuple[float, ...]
    gain_reduction_db: float = 0.0
    input_clipped: bool = False
    output_clipped: bool = False

    @staticmethod
    def silent(channels: int) -> "MeterSnapshot":
        floor = tuple([FLOOR_DB] * channels)
        return MeterSnapshot(floor, floor, floor, floor)


def measure(x: np.ndarray) -> tuple[tuple[float, ...], tuple[float, ...], bool]:
    """Returnerar (peak_db per kanal, rms_db per kanal, clipping)."""
    if x.size == 0:
        floor = tuple([FLOOR_DB] * x.shape[1])
        return floor, floor, False
    peak = np.max(np.abs(x), axis=0)
    rms = np.sqrt(np.mean(np.square(x, dtype=np.float64), axis=0))
    clipped = bool(np.any(peak >= CLIP_THRESHOLD))
    return (
        tuple(lin_to_db(float(p)) for p in peak),
        tuple(lin_to_db(float(r)) for r in rms),
        clipped,
    )
