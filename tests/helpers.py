from __future__ import annotations

import numpy as np

from autodsp.audio.core import RealtimeCore
from autodsp.audio.source import FileSource
from autodsp.dsp.params import ChainSettings
from autodsp.safety import SafetyReport


def sine(freq: float, fs: int, seconds: float, amp: float = 0.5, channels: int = 2) -> np.ndarray:
    t = np.arange(int(fs * seconds)) / fs
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.repeat(mono[:, None], channels, axis=1)


def flat_settings(**changes) -> ChainSettings:
    base = dict(master_gain_db=0.0)
    base.update(changes)
    return ChainSettings().replace(**base)


def make_core(
    settings: ChainSettings | None = None,
    fs: int = 48000,
    seconds: float = 4.0,
    amp: float = 0.5,
    armed: bool = True,
    loop: bool = True,
    play: bool = True,
) -> RealtimeCore:
    """Virtuell ljudenhet: kärnan drivs direkt av testet, utan PortAudio eller hårdvara."""
    core = RealtimeCore(fs, 2, settings or flat_settings())
    core.set_source(FileSource(sine(1000, fs, seconds, amp), fs, fs, loop=loop))
    if armed:
        core.safety.arm(SafetyReport((), 0.0), acknowledged=True)
    if play:
        core.play()
    return core


def run_blocks(core: RealtimeCore, n_blocks: int, block: int = 512) -> np.ndarray:
    return np.concatenate([core.process_block(block) for _ in range(n_blocks)], axis=0)
