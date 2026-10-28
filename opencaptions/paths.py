from __future__ import annotations

import os
from pathlib import Path

PARAKEET_DIR = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"


def data_dir() -> Path:
    env = os.environ.get("OPENCAPTIONS_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "opencaptions"
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "opencaptions"


def models_dir() -> Path:
    return data_dir() / "models"


def fonts_dir() -> Path:
    return data_dir() / "fonts"


def jobs_dir() -> Path:
    return data_dir() / "jobs"


def parakeet_path() -> Path:
    return models_dir() / PARAKEET_DIR
