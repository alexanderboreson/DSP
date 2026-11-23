"""Inställningsmodeller för signalkedjan.

Alla modeller är oföränderliga (frozen) och validerade av pydantic. NaN och
oändliga värden förkastas redan vid inläsning, vilket gör att samma modeller
kan användas både för GUI-state och för JSON-presets.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BandKind = Literal["peak", "low_shelf", "high_shelf"]

MIN_FREQ_HZ = 20.0
MAX_FREQ_HZ = 20_000.0
MAX_BANDS = 16
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 384_000
MAX_FREQ_FRACTION_OF_FS = 0.45


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class EQBand(_Frozen):
    kind: BandKind = "peak"
    freq_hz: float = Field(default=1000.0, ge=MIN_FREQ_HZ, le=MAX_FREQ_HZ)
    gain_db: float = Field(default=0.0, ge=-24.0, le=24.0)
    q: float = Field(default=1.0, ge=0.1, le=20.0)
    enabled: bool = True


def default_bands() -> tuple[EQBand, ...]:
    freqs = (60, 120, 250, 500, 1000, 2000, 4000, 8000, 12000, 16000)
    bands: list[EQBand] = []
    for i, f in enumerate(freqs):
        if i == 0:
            bands.append(EQBand(kind="low_shelf", freq_hz=f, q=0.707))
        elif i == len(freqs) - 1:
            bands.append(EQBand(kind="high_shelf", freq_hz=f, q=0.707))
        else:
            bands.append(EQBand(kind="peak", freq_hz=f, q=1.0))
    return tuple(bands)


class ChainSettings(_Frozen):
    # Konservativa standardvärden: master -12 dB, limiter -1 dBFS.
    input_gain_db: float = Field(default=0.0, ge=-60.0, le=12.0)
    master_gain_db: float = Field(default=-12.0, ge=-80.0, le=6.0)
    mute: bool = False
    eq_bypass: bool = False
    eq_bands: tuple[EQBand, ...] = Field(
        default_factory=default_bands, min_length=1, max_length=MAX_BANDS
    )
    limiter_threshold_db: float = Field(default=-1.0, ge=-24.0, le=-0.1)
    limiter_release_ms: float = Field(default=100.0, ge=10.0, le=1000.0)

    def replace(self, **changes: object) -> "ChainSettings":
        """Returnerar en ny, validerad kopia med ändringarna applicerade."""
        return type(self).model_validate({**self.model_dump(), **changes})

    def with_band(self, index: int, band: EQBand) -> "ChainSettings":
        bands = list(self.eq_bands)
        bands[index] = band
        return self.replace(eq_bands=tuple(bands))


def validate_for_sample_rate(settings: ChainSettings, fs: float) -> None:
    """Kontrollerar att inställningarna är rimliga vid given samplingsfrekvens."""
    if not (MIN_SAMPLE_RATE <= fs <= MAX_SAMPLE_RATE):
        raise ValueError(
            f"Samplingsfrekvensen {fs} Hz stöds inte "
            f"({MIN_SAMPLE_RATE}-{MAX_SAMPLE_RATE} Hz)."
        )
    limit = MAX_FREQ_FRACTION_OF_FS * fs
    for i, band in enumerate(settings.eq_bands):
        if band.freq_hz > limit:
            raise ValueError(
                f"EQ-band {i + 1}: {band.freq_hz:.0f} Hz ligger för nära "
                f"Nyquist vid {fs:.0f} Hz (max {limit:.0f} Hz)."
            )
