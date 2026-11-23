"""Qt-oberoende inställningslager med ångra/gör om och A/B-jämförelse."""

from __future__ import annotations

import time
from typing import Callable

from .dsp.params import ChainSettings


class SettingsStore:
    def __init__(
        self,
        initial: ChainSettings | None = None,
        history_limit: int = 200,
        coalesce_window_s: float = 0.6,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._current = initial or ChainSettings()
        self._undo: list[ChainSettings] = []
        self._redo: list[ChainSettings] = []
        self._limit = history_limit
        self._window = coalesce_window_s
        self._clock = clock
        self._last_key: str | None = None
        self._last_time = 0.0
        self._subscribers: list[Callable[[ChainSettings], None]] = []
        self._slots = {"A": self._current, "B": self._current}
        self.active_slot = "A"

    @property
    def current(self) -> ChainSettings:
        return self._current

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def subscribe(self, callback: Callable[[ChainSettings], None]) -> None:
        self._subscribers.append(callback)

    def _notify(self) -> None:
        for cb in list(self._subscribers):
            cb(self._current)

    def set(self, settings: ChainSettings, coalesce_key: str | None = None) -> None:
        if settings == self._current:
            return
        now = self._clock()
        coalesce = (
            coalesce_key is not None
            and coalesce_key == self._last_key
            and now - self._last_time <= self._window
        )
        if not coalesce:
            self._undo.append(self._current)
            if len(self._undo) > self._limit:
                del self._undo[0]
        self._redo.clear()
        self._current = settings
        self._last_key = coalesce_key
        self._last_time = now
        self._notify()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._current)
        self._current = self._undo.pop()
        self._last_key = None
        self._notify()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._current)
        self._current = self._redo.pop()
        self._last_key = None
        self._notify()
        return True

    def toggle_ab(self) -> str:
        """Sparar aktuella inställningar i aktiv slot och växlar till den andra."""
        self._slots[self.active_slot] = self._current
        self.active_slot = "B" if self.active_slot == "A" else "A"
        self.set(self._slots[self.active_slot])
        return self.active_slot
