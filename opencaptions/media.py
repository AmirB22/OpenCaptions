"""Thin wrappers around ffmpeg / ffprobe."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class MediaError(RuntimeError):
    pass


def run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise MediaError(f"{cmd[0]} failed: {p.stderr[-800:]}")
    return p


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: str          # rational, e.g. "24" or "30000/1001"
    duration: float
    has_audio: bool


def probe(video: Path | str) -> VideoInfo:
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(video)])
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise MediaError("no video stream")
    has_audio = any(s["codec_type"] == "audio" for s in d["streams"])
    fps = v.get("avg_frame_rate") or v.get("r_frame_rate") or "30"
    if fps in ("0/0", ""):
        fps = v.get("r_frame_rate", "30")
    dur = float(d["format"].get("duration") or v.get("duration") or 0)
    return VideoInfo(int(v["width"]), int(v["height"]), fps, dur, has_audio)


def extract_audio(video: Path | str, wav_path: Path | str) -> None:
    run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav_path)])


def read_wav(path: Path | str) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return x, sr


def energy_envelope(x: np.ndarray, sr: int, win: float = 0.02) -> np.ndarray:
    n = max(1, int(win * sr))
    return np.convolve(x ** 2, np.ones(n) / n, "same")


def detect_scenes(video: Path | str, threshold: float = 0.18) -> list[float]:
    """Return times (s) of hard cuts. Neighbouring detections closer than 0.2 s are merged."""
    p = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(video), "-an",
         "-vf", f"scale=240:-1,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    times = sorted(float(m) for m in re.findall(r"pts_time:([0-9.]+)", p.stderr))
    out: list[float] = []
    for t in times:
        if not out or t - out[-1] > 0.2:
            out.append(t)
    return out


def ffprobe_video_duration(path: Path | str) -> float:
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
             "-of", "csv=p=0", str(path)])
    return float(p.stdout.strip())


_checked = False


def check_ffmpeg() -> None:
    """Fail early with a useful message if ffmpeg is missing or built without libass (needed for captions)."""
    global _checked
    if _checked:
        return
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise MediaError(
                f"{tool} not found on PATH. Linux: install ffmpeg with your package manager. "
                "Windows: winget install Gyan.FFmpeg, then open a new terminal.")
    p = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    if not re.search(r"\bass\b", p.stdout):
        raise MediaError("this ffmpeg build has no 'ass' filter (libass). Use a full build, "
                         "on Windows the Gyan.FFmpeg package has it.")
    _checked = True
