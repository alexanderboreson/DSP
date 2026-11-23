from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        path = base / "AutoDSP Studio"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        path = base / "autodsp-studio"
    path.mkdir(parents=True, exist_ok=True)
    return path
