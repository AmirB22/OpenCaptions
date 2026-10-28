"""Speech to text with word start times (NVIDIA Parakeet TDT through sherpa-onnx). English only."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from . import paths
from .media import read_wav

FILLERS = {"mm", "hmm", "uh", "um", "mhm", "uh-huh"}


def _recognizer():
    import sherpa_onnx

    d = paths.parakeet_path()
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(d / "encoder.int8.onnx"),
        decoder=str(d / "decoder.int8.onnx"),
        joiner=str(d / "joiner.int8.onnx"),
        tokens=str(d / "tokens.txt"),
        num_threads=4,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        model_type="nemo_transducer",
    )


def _chunk_bounds(x: np.ndarray, sr: int, chunk_s: float = 20.0) -> list[int]:
    """Cut long audio into ~20 s pieces, each cut placed at the quietest point near the boundary."""
    step = int(chunk_s * sr)
    cuts = [0]
    while cuts[-1] + step < len(x):
        a = cuts[-1] + step
        seg = x[a - sr: a + sr]
        e = np.convolve(seg ** 2, np.ones(800) / 800, "same")
        cuts.append(a - sr + int(np.argmin(e)))
    cuts.append(len(x))
    return cuts


def _merge_tokens(tokens: list[str], times: list[float]) -> list[dict]:
    words: list[dict] = []
    cur, start = "", None
    for tok, tm in zip(tokens, times):
        if tok.startswith("▁") or tok.startswith(" "):
            if cur:
                words.append({"w": cur, "t": round(float(start), 3)})
            cur, start = tok.lstrip("▁ "), tm
        else:
            if not cur:
                start = tm
            cur += tok
    if cur:
        words.append({"w": cur, "t": round(float(start), 3)})
    return words


def _drop_tail_fillers(words: list[dict], duration: float) -> list[dict]:
    while words and re.sub(r"[^a-z\-]", "", words[-1]["w"].lower()) in FILLERS and words[-1]["t"] > duration - 0.5:
        words.pop()
    return words


_CYR = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "Đ", "Е": "E", "Ж": "Ž", "З": "Z", "И": "I",
    "Ј": "J", "К": "K", "Л": "L", "Љ": "Lj", "М": "M", "Н": "N", "Њ": "Nj", "О": "O", "П": "P", "Р": "R",
    "С": "S", "Т": "T", "Ћ": "Ć", "У": "U", "Ф": "F", "Х": "H", "Ц": "C", "Ч": "Č", "Џ": "Dž", "Ш": "Š",
}
_CYR.update({k.lower(): v.lower() for k, v in list(_CYR.items())})


def to_latin(text: str) -> str:
    """Serbian Cyrillic to Latin script. Text that is already Latin is returned unchanged.
    The digraph letters become LJ/NJ/DŽ inside upper case words and Lj/Nj/Dž otherwise."""
    out: list[str] = []
    for i, ch in enumerate(text):
        rep = _CYR.get(ch)
        if rep is None:
            out.append(ch)
            continue
        if ch in "ЉЊЏ":
            nxt = text[i + 1] if i + 1 < len(text) else ""
            prv = text[i - 1] if i > 0 else ""
            if (nxt.isalpha() and nxt.isupper()) or (prv.isalpha() and prv.isupper()):
                rep = rep.upper()
        out.append(rep)
    return "".join(out)


def whisper_words(raw: list[tuple[str, float]], language: str) -> list[dict]:
    """(token text, start) pairs from Whisper to our word list. Standalone punctuation joins the previous word."""
    words: list[dict] = []
    for text, start in raw:
        t = text.strip()
        if not t:
            continue
        if language.lower()[:2] in ("sr", "hr", "bs"):
            t = to_latin(t)
        if words and re.fullmatch(r"[.,!?;:…]+", t):
            words[-1]["w"] += t
            continue
        words.append({"w": t, "t": round(float(start), 3)})
    return words


def transcribe_whisper(wav_path: Path | str, duration: float, language: str, model_size: str = "medium",
                       progress=None) -> list[dict]:
    """Any language Whisper knows. Needs: pip install -e '.[whisper]'. The model is
    downloaded on first use (medium is about 1.5 GB)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("the Whisper engine needs the extra dependency: pip install -e '.[whisper]'") from e
    import os

    try:
        model = WhisperModel(model_size, device=os.environ.get("OPENCAPTIONS_DEVICE", "cpu"), compute_type="int8",
                             download_root=str(paths.models_dir() / "whisper"))
    except Exception as e:
        raise RuntimeError(f"could not load the Whisper model '{model_size}'. The first run downloads it from "
                           f"Hugging Face, so it needs internet access. Original error: {e}") from e
    segments, _info = model.transcribe(str(wav_path), language=language, word_timestamps=True,
                                       vad_filter=True, beam_size=5, condition_on_previous_text=False)
    raw: list[tuple[str, float]] = []
    for seg in segments:
        for w in seg.words or []:
            raw.append((w.word, w.start))
        if progress and duration:
            progress(min(1.0, seg.end / duration))
    return _drop_tail_fillers(whisper_words(raw, language), duration)


def transcribe(wav_path: Path | str, duration: float, progress=None, language: str = "en",
               engine: str = "auto", whisper_model: str = "medium") -> list[dict]:
    if engine == "auto":
        engine = "parakeet" if language.lower().startswith("en") else "whisper"
    if engine == "whisper":
        return transcribe_whisper(wav_path, duration, language, whisper_model, progress)
    if not language.lower().startswith("en"):
        raise RuntimeError("the Parakeet model is English only, use --engine whisper for other languages")
    from .models import model_ready

    if not model_ready():
        raise RuntimeError("speech model missing, run: opencaptions models fetch")
    x, sr = read_wav(wav_path)
    rec = _recognizer()
    cuts = _chunk_bounds(x, sr)
    tokens: list[str] = []
    times: list[float] = []
    for i, (a, b) in enumerate(zip(cuts, cuts[1:])):
        s = rec.create_stream()
        s.accept_waveform(sr, x[a:b])
        rec.decode_stream(s)
        r = s.result
        for t, tm in zip(r.tokens, r.timestamps):
            tokens.append(t)
            times.append(tm + a / sr)
        if progress:
            progress((i + 1) / (len(cuts) - 1))
    return _drop_tail_fillers(_merge_tokens(tokens, times), duration)
