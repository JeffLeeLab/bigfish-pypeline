from __future__ import annotations

import pathlib
import sys

APP_DIR = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
SRC_DIR = REPO_ROOT / "src"

for path in (APP_DIR, SRC_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)