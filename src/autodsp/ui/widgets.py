from __future__ import annotations

import math
import time
from typing import Sequence

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..dsp.params import MAX_FREQ_HZ, MIN_FREQ_HZ, EQBand
from ..dsp.response import eq_response_db, log_freq_grid
from .theme import COLORS

LOG_MIN = math.log10(MIN_FREQ_HZ)
LOG_MAX = math.log10(MAX_FREQ_HZ)
FREQ_TICKS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]


def _freq_label(f: int) -> str:
    return f"{f // 1000}k" if f >= 1000 else str(f)


def style_plot(plot: pg.PlotWidget) -> None:
    plot.setBackground(COLORS["panel"])
    item = plot.getPlotItem()
    item.showGrid(x=True, y=True, alpha=0.2)
    item.hideButtons()
    item.setMenuEnabled(False)
    axis = item.getAxis("bottom")
    axis.setTicks([[(math.log10(f), _freq_label(f)) for f in FREQ_TICKS]])
    axis.setLabel("Frekvens", units="Hz")
    for name in ("bottom", "left"):
        item.getAxis(name).setTextPen(COLORS["muted"])
        item.getAxis(name).setPen(COLORS["border"])


class LevelMeter(QWidget):
    """Vertikal nivåmätare i dBFS med toppmarkering (peak hold)."""

    FLOOR = -60.0

    def __init__(self, channels: int = 2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._peaks = [-120.0] * channels
        self._holds = [-120.0] * channels
        self._hold_t = [0.0] * channels
        self.setMinimumSize(70, 140)

    def set_levels(self, peak_db: Sequence[float]) -> None:
        now = time.monotonic()
        for i in range(min(len(peak_db), len(self._peaks))):
            p = float(peak_db[i])
            self._peaks[i] = p
            if p >= self._holds[i] or now - self._hold_t[i] > 1.5:
                self._holds[i] = p
                self._hold_t[i] = now
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(COLORS["panel2"]))
        n = len(self._peaks)
        gap = 6
        bar_w = (w - gap * (n + 1)) / n
        span = h - 8
        for i, db in enumerate(self._peaks):
            frac = max(0.0, min(1.0, (db - self.FLOOR) / -self.FLOOR))
            color = COLORS["red"] if db >= -3 else COLORS["orange"] if db >= -12 else COLORS["green"]
            x = gap + i * (bar_w + gap)
            bar_h = frac * span
            p.fillRect(QRectF(x, h - 4 - bar_h, bar_w, bar_h), QColor(color))
            hold_frac = max(0.0, min(1.0, (self._holds[i] - self.FLOOR) / -self.FLOOR))
            y = h - 4 - hold_frac * span
            p.setPen(QPen(QColor(COLORS["cyan"]), 2))
            p.drawLine(int(x), int(y), int(x + bar_w), int(y))
        p.end()


class EqGraph(pg.PlotWidget):
    """Interaktiv EQ-graf. Svarskurvan är beräknad (matematisk modell), inte uppmätt.

    Punkter flyttas med musen; numerisk inmatning görs i tabellen bredvid.
    """

    bandMoved = pyqtSignal(int, float, float, bool)  # index, Hz, dB, klar

    def __init__(self, fs: float = 48000.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fs = float(fs)
        style_plot(self)
        item = self.getPlotItem()
        item.setMouseEnabled(False, False)
        self.setXRange(LOG_MIN, LOG_MAX, padding=0)
        self.setYRange(-24, 24, padding=0)
        item.getAxis("left").setLabel("Förstärkning", units="dB")
        item.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(COLORS["border"], width=1)))
        self._curve = item.plot(pen=pg.mkPen(COLORS["cyan"], width=2))
        self._freqs = log_freq_grid(512)
        self._x = np.log10(self._freqs)
        self._targets: list[pg.TargetItem] = []
        self._guard = False

    def set_fs(self, fs: float) -> None:
        self.fs = float(fs)

    def set_bands(self, bands: Sequence[EQBand]) -> None:
        self._guard = True
        try:
            if len(self._targets) != len(bands):
                for t in self._targets:
                    self.getPlotItem().removeItem(t)
                self._targets = []
                for i in range(len(bands)):
                    t = pg.TargetItem(
                        pos=(0, 0),
                        size=13,
                        symbol="o",
                        movable=True,
                        pen=pg.mkPen(COLORS["cyan"], width=2),
                        hoverPen=pg.mkPen(COLORS["text"], width=2),
                        brush=pg.mkBrush(COLORS["panel2"]),
                    )
                    t.sigPositionChanged.connect(lambda it, i=i: self._on_move(i, it, False))
                    t.sigPositionChangeFinished.connect(lambda it, i=i: self._on_move(i, it, True))
                    self.getPlotItem().addItem(t)
                    self._targets.append(t)
            for t, b in zip(self._targets, bands):
                x, y = math.log10(b.freq_hz), b.gain_db
                pos = t.pos()
                if abs(pos.x() - x) > 1e-6 or abs(pos.y() - y) > 1e-6:
                    t.setPos((x, y))
                t.setPen(pg.mkPen(COLORS["cyan"] if b.enabled else COLORS["muted"], width=2))
            resp = eq_response_db(bands, self.fs, self._freqs)
            self._curve.setData(self._x, resp)
        finally:
            self._guard = False

    def _on_move(self, index: int, item: pg.TargetItem, finished: bool) -> None:
        if self._guard:
            return
        pos = item.pos()
        x = min(max(pos.x(), LOG_MIN), LOG_MAX)
        y = min(max(pos.y(), -24.0), 24.0)
        if abs(x - pos.x()) > 1e-9 or abs(y - pos.y()) > 1e-9:
            self._guard = True
            try:
                item.setPos((x, y))
            finally:
                self._guard = False
        self.bandMoved.emit(index, 10.0**x, float(y), finished)


class SpectrumPlot(pg.PlotWidget):
    """FFT-spektrum av utsignalen (dBFS). Ej en akustisk mätning."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        style_plot(self)
        self.getPlotItem().setMouseEnabled(False, False)
        self.setXRange(LOG_MIN, LOG_MAX, padding=0)
        self.setYRange(-100, 0, padding=0)
        self.getPlotItem().getAxis("left").setLabel("Nivå", units="dBFS")
        self._curve = self.getPlotItem().plot(pen=pg.mkPen(COLORS["cyan"], width=1.5))

    def update_spectrum(self, freqs: np.ndarray, db: np.ndarray) -> None:
        self._curve.setData(np.log10(freqs[1:]), db[1:])
