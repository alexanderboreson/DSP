"""Ljudfilsläsning och uppspelningskälla (hela filen laddas i minnet i Fas 1)."""

from __future__ import annotations

from math import gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

MAX_DURATION_S = 3600.0


def load_audio_file(path: str | Path) -> tuple[np.ndarray, int]:
    """Läser en ljudfil till (frames, kanaler) float32 och samplingsfrekvens.

    Använder soundfile om det finns, annars en WAV-läsare via SciPy.
    """
    p = Path(path)
    try:
        import soundfile as sf  # type: ignore
    except ImportError:
        sf = None

    if sf is not None:
        data, sr = sf.read(str(p), dtype="float32", always_2d=True)
    else:
        if p.suffix.lower() != ".wav":
            raise ValueError("Endast WAV stöds utan paketet 'soundfile'. Installera soundfile.")
        from scipy.io import wavfile

        sr, raw = wavfile.read(str(p))
        if raw.ndim == 1:
            raw = raw[:, None]
        if raw.dtype == np.int16:
            data = raw.astype(np.float32) / 32768.0
        elif raw.dtype == np.int32:
            data = raw.astype(np.float32) / 2147483648.0
        elif raw.dtype == np.uint8:
            data = (raw.astype(np.float32) - 128.0) / 128.0
        elif raw.dtype in (np.float32, np.float64):
            data = raw.astype(np.float32)
        else:
            raise ValueError(f"WAV-format stöds inte: {raw.dtype}")

    if data.shape[0] / float(sr) > MAX_DURATION_S:
        raise ValueError("Filen är för lång (max 60 minuter i Fas 1).")
    return np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0), int(sr)


class FileSource:
    """Stereokälla. Mono dupliceras, fler än två kanaler -> de två första används."""

    def __init__(self, data: np.ndarray, sr: int, target_sr: int, loop: bool = False) -> None:
        data = np.asarray(data, dtype=np.float32)
        if data.ndim != 2 or data.shape[1] < 1:
            raise ValueError("Ogiltig ljuddata.")
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        if sr != target_sr:
            g = gcd(int(sr), int(target_sr))
            data = resample_poly(data, target_sr // g, sr // g, axis=0).astype(np.float32)
        self._data = np.ascontiguousarray(data)
        self.fs = int(target_sr)
        self.loop = loop
        self.finished = False
        self._pos = 0

    @property
    def length(self) -> int:
        return self._data.shape[0]

    @property
    def position(self) -> int:
        return self._pos

    def seek(self, frame: int) -> None:
        self._pos = max(0, min(int(frame), self.length))
        self.finished = False

    def read(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, 2), dtype=np.float32)
        filled = 0
        n = self.length
        while filled < frames:
            avail = n - self._pos
            if avail <= 0:
                if self.loop and n > 0:
                    self._pos = 0
                    continue
                self.finished = True
                break
            take = min(avail, frames - filled)
            out[filled : filled + take] = self._data[self._pos : self._pos + take]
            self._pos += take
            filled += take
        return out
