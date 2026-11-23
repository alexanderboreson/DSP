from __future__ import annotations

import math

FLOOR_DB = -120.0


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def lin_to_db(lin: float) -> float:
    """Linjär amplitud -> dB. Returnerar FLOOR_DB för 0, negativa tal och NaN."""
    if not (lin > 1e-6):
        return FLOOR_DB
    return 20.0 * math.log10(lin)
