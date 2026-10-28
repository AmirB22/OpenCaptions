"""analyze: transcript + scenes. render: cut to chosen sentences and burn captions."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path, PurePath
from typing import Callable

from . import paths
from .captions import build_ass, norm
from .media import (MediaError, check_ffmpeg, detect_scenes, energy_envelope, extract_audio, ffprobe_video_duration,
                    probe, read_wav, run)
from .plan import group_runs, parse_keep, plan_segments, split_sentences
from .styles import Hook, Style, resolve
from .transcribe import transcribe

Progress = Callable[[str, float], None]


def _noop(stage: str, frac: float) -> None:
    pass


def analyze(video: Path | str, workdir: Path | str, progress: Progress | None = None,
            language: str = "en", engine: str = "auto", whisper_model: str = "medium") -> dict:
    progress = progress or _noop
    check_ffmpeg()
    video, workdir = Path(video), Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    if not info.has_audio:
        raise MediaError("the video has no audio track")
    progress("audio", 0.0)
    wav = workdir / "audio.wav"
    extract_audio(video, wav)
    progress("transcribe", 0.0)
    words = transcribe(wav, info.duration, progress=lambda f: progress("transcribe", f),
                       language=language, engine=engine, whisper_model=whisper_model)
    progress("scenes", 0.0)
    scenes = detect_scenes(video)
    sentences = split_sentences(words, info.duration)
    data = {
        "video": str(video), "duration": info.duration, "width": info.width, "height": info.height,
        "fps": info.fps, "words": words, "sentences": sentences, "scenes": scenes, "language": language,
    }
    (workdir / "analysis.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    progress("done", 1.0)
    return data


def load_analysis(workdir: Path | str) -> dict:
    return json.loads((Path(workdir) / "analysis.json").read_text(encoding="utf-8"))


def apply_fixes(words: list[dict], fixes: list[str]) -> list[dict]:
    """Replace single words, e.g. 'wright=right'. Trailing punctuation is kept."""
    table: dict[str, str] = {}
    for f in fixes:
        if "=" in f:
            a, b = f.split("=", 1)
            table[norm(a)] = b.strip()
    out = []
    for w in words:
        core = w["w"].rstrip(",.?!\"')")
        tail = w["w"][len(core):]
        rep = table.get(norm(core))
        out.append({**w, "w": (rep + tail) if rep is not None else w["w"]})
    return out


def apply_edits(words: list[dict], edits: dict[int, str] | None) -> list[dict]:
    """Replace words by index (from the web UI). Trailing punctuation is kept, an empty text is ignored."""
    if not edits:
        return words
    out = list(words)
    for i, text in edits.items():
        text = text.strip()
        if text and 0 <= int(i) < len(out):
            w = out[int(i)]["w"]
            tail = w[len(w.rstrip(",.?!\"')")):]
            out[int(i)] = {**out[int(i)], "w": text + tail}
    return out


def _filter_path(p: "str | PurePath") -> str:
    """Quote a path for an ffmpeg filter option. Forward slashes and an escaped drive colon work on
    both Linux and Windows (C:\\fonts becomes 'C\\:/fonts')."""
    posix = p.as_posix() if isinstance(p, PurePath) else Path(p).as_posix()
    return "'" + posix.replace("'", "'\\''").replace(":", "\\:") + "'"


def _burn_cmd(inputs: list[str], ass: str, out: str, copy_audio: bool, preset: str, crf: int,
              clean: bool = True) -> list[str]:
    fonts = _filter_path(str(paths.fonts_dir()))
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-vf", f"ass={ass}:fontsdir={fonts}",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "copy"] if copy_audio else ["-c:a", "aac", "-b:a", "160k"]
    if clean:
        cmd += ["-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                "-flags:a", "+bitexact"]
    cmd += ["-movflags", "+faststart", out]
    return cmd


def render(video: Path | str, workdir: Path | str, keep: str | list[int], style: Style | str | dict | None,
           out: Path | str, brand: list[str] | None = None, fixes: list[str] | None = None,
           progress: Progress | None = None, preset: str = "veryfast", crf: int = 20,
           hook: Hook | None = None, clean: bool = True, edits: dict[int, str] | None = None) -> dict:
    progress = progress or _noop
    check_ffmpeg()
    video, workdir, out = Path(video), Path(workdir), Path(out)
    data = load_analysis(workdir)
    lang = data.get("language", "en")
    st = style if isinstance(style, Style) else resolve(style)
    words = apply_edits(apply_fixes(data["words"], fixes or []), edits)
    sentences = data["sentences"]
    keep_idx = parse_keep(keep, len(sentences))
    if not keep_idx:
        raise ValueError("no sentences selected")
    phrases = [[norm(t) for t in b.split()] for b in (brand or []) if b.strip()]
    duration, width, height = data["duration"], data["width"], data["height"]
    out.parent.mkdir(parents=True, exist_ok=True)

    if keep_idx == list(range(len(sentences))):
        # no cuts: captions straight onto the source
        progress("captions", 0.0)
        ass = build_ass([w["w"] for w in words], [w["t"] for w in words], duration, st, width, height, phrases, hook=hook,
                        language=lang)
        (workdir / "captions.ass").write_text(ass, encoding="utf-8")
        progress("render", 0.0)
        run_in(_burn_cmd(["-i", str(video.resolve())], "captions.ass", str(out.resolve()), True, preset, crf, clean), workdir)
        progress("done", 1.0)
        return {"output": str(out), "duration": duration, "segments": 1}

    wav = workdir / "audio.wav"
    if not wav.exists():
        extract_audio(video, wav)
    x, sr = read_wav(wav)
    env = energy_envelope(x, sr)
    groups = group_runs(keep_idx)
    fps_val = _fps_float(data["fps"])
    plan = plan_segments(words, sentences, groups, data["scenes"], env, sr, duration, fps=fps_val)

    parts_dir = workdir / "parts"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir()
    src = str(video.resolve())
    part_durs: list[float] = []
    for i, p in enumerate(plan):
        progress("cut", i / len(plan))
        fo = round(p["dur"] - 0.03, 3)
        vf = (f"[0:v]fps={data['fps']},trim=duration={p['vdur']},setpts=PTS-STARTPTS,"
              f"tpad=stop_mode=clone:stop_duration=1[v];"
              f"[1:a]afade=t=in:d=0.02,afade=t=out:st={fo}:d=0.03[a]")
        part = parts_dir / f"p{i}.mp4"
        run(["ffmpeg", "-v", "error", "-y",
             "-ss", str(p["v0"]), "-i", src,
             "-ss", str(p["astart"]), "-t", str(p["dur"]), "-i", src,
             "-filter_complex", vf, "-map", "[v]", "-map", "[a]", "-t", str(p["dur"]),
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "17", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(part)])
        part_durs.append(ffprobe_video_duration(part))

    # captions follow the audio (picture and sound of one clip start together on the new timeline)
    Wn: list[str] = []
    Tn: list[float] = []
    cum = 0.0
    for p, vd in zip(plan, part_durs):
        g = p["group"]
        a, b = sentences[g[0]]["a"], sentences[g[-1]]["b"]
        for k in range(a, b + 1):
            t = words[k]["t"]
            if p["astart"] - 0.05 <= t <= p["aend"] + 0.02:
                Wn.append(words[k]["w"])
                Tn.append(t - p["astart"] + cum)
        cum += vd
    progress("captions", 0.0)
    (workdir / "captions.ass").write_text(
        build_ass(Wn, Tn, cum, st, width, height, phrases, hook=hook, language=lang), encoding="utf-8")
    (workdir / "parts.txt").write_text(
        "".join(f"file 'parts/p{i}.mp4'\n" for i in range(len(plan))), encoding="utf-8")
    progress("render", 0.0)
    cmd = _burn_cmd(["-f", "concat", "-safe", "0", "-i", "parts.txt"], "captions.ass", str(out.resolve()), False, preset, crf, clean)
    run_in(cmd, workdir)
    shutil.rmtree(parts_dir, ignore_errors=True)
    progress("done", 1.0)
    return {"output": str(out), "duration": cum, "segments": len(plan)}


def _fps_float(r: str) -> float:
    if "/" in r:
        a, b = r.split("/")
        return float(a) / float(b) if float(b) else 24.0
    return float(r)


def run_in(cmd: list[str], cwd: Path) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))
    if p.returncode != 0:
        raise MediaError(f"ffmpeg failed: {p.stderr[-800:]}")

