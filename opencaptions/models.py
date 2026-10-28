"""Download the speech model and fonts from GitHub (nothing is bundled in the repo)."""
from __future__ import annotations

import io
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from . import paths
from .styles import FONTS

PARAKEET_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
                "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2")
INTER_URL = "https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip"
INTER_FILES = {"Inter-SemiBold.ttf", "Inter-Bold.ttf"}
FONT_URLS = {
    "Montserrat-SemiBold.ttf": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-SemiBold.ttf",
    "Montserrat-Bold.ttf": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Bold.ttf",
    "Montserrat-ExtraBold.ttf": "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-ExtraBold.ttf",
    "Tinos-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/tinos/Tinos-Regular.ttf",
    "BebasNeue-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
}


def _download(url: str, label: str) -> bytes:
    print(f"downloading {label} ...", file=sys.stderr)
    with urllib.request.urlopen(url) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            buf.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1e6:.0f}/{total / 1e6:.0f} MB", end="", file=sys.stderr)
        if total:
            print(file=sys.stderr)
    return buf.getvalue()


def model_ready() -> bool:
    d = paths.parakeet_path()
    return all((d / f).exists() for f in ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"))


def installed_fonts() -> dict[str, bool]:
    return {k: (paths.fonts_dir() / f.filename).exists() for k, f in FONTS.items()}


def fetch_model() -> None:
    if model_ready():
        print("speech model already present", file=sys.stderr)
        return
    data = _download(PARAKEET_URL, "speech model (about 480 MB)")
    paths.models_dir().mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as t:
        t.extractall(paths.models_dir())


def extract_inter(zip_bytes: bytes, dest: Path) -> list[str]:
    """Pull the static Inter files out of the release zip. Entries look like 'extras/ttf/Inter-Bold.ttf'."""
    got: list[str] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            norm = name.replace("\\", "/")
            base = norm.rsplit("/", 1)[-1]
            if base in INTER_FILES and "extras/ttf/" in norm:
                (dest / base).write_bytes(z.read(name))
                got.append(base)
    missing = INTER_FILES - set(got)
    if missing:
        raise RuntimeError(f"Inter archive did not contain: {', '.join(sorted(missing))}")
    return got


def fetch_fonts() -> None:
    paths.fonts_dir().mkdir(parents=True, exist_ok=True)
    have = installed_fonts()
    if not (have["inter-semibold"] and have["inter-bold"]):
        extract_inter(_download(INTER_URL, "Inter (about 28 MB)"), paths.fonts_dir())
    for fname, url in FONT_URLS.items():
        target = paths.fonts_dir() / fname
        if not target.exists():
            target.write_bytes(_download(url, fname))


def status() -> str:
    lines = [f"data dir: {paths.data_dir()}",
             f"speech model: {'ok' if model_ready() else 'missing (opencaptions models fetch)'}"]
    for k, v in installed_fonts().items():
        lines.append(f"font {k}: {'ok' if v else 'missing'}")
    return "\n".join(lines)
