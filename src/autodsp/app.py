from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import user_data_dir


def _configure_logging() -> None:
    handler = RotatingFileHandler(
        user_data_dir() / "autodsp.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main() -> int:
    _configure_logging()
    log = logging.getLogger("autodsp")

    import pyqtgraph as pg
    from PyQt6.QtWidgets import QApplication

    from .audio.engine import AudioEngine
    from .presets import PresetLibrary, load_preset
    from .store import SettingsStore
    from .ui.main_window import MainWindow
    from .ui.theme import COLORS, stylesheet

    app = QApplication(sys.argv)
    app.setStyleSheet(stylesheet())
    pg.setConfigOptions(antialias=True, background=COLORS["panel"], foreground=COLORS["muted"])

    data_dir = user_data_dir()
    autosave = data_dir / "autosave.json"
    initial = None
    if autosave.exists():
        try:
            initial = load_preset(autosave).settings
        except Exception:  # noqa: BLE001 - trasig autosave ska aldrig hindra start
            log.warning("Ignorerar ogiltig autosave", exc_info=True)

    store = SettingsStore(initial)
    engine = AudioEngine(settings=store.current)  # utgången startar alltid avstängd
    library = PresetLibrary(data_dir / "presets")

    window = MainWindow(engine, store, library, autosave_path=autosave)
    window.resize(1280, 820)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
