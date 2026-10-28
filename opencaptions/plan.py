"""Sentence splitting and cut planning.

The audio is cut on quiet points between sentences. The picture is cut separately, so that every
clip starts and ends inside a whole scene of the source video. That is what prevents the one or two
frame flashes of a neighbouring scene at the joins.
"""
from __future__ import annotations

import re

import numpy as np

FRAME_TAIL_MARGIN = 0.07   # stop the picture this long before a scene boundary and hold the last frame
MIN_FRAGMENT = 0.6         # a visible piece of a scene shorter than this counts as a flash


def split_sentences(words: list[dict], duration: float) -> list[dict]:
    out: list[dict] = []
    s = 0
    for i, w in enumerate(words):
        if re.search(r"[.?!][\"')]*$", w["w"]):
            out.append(_sentence(len(out), words, s, i, duration))
            s = i + 1
    if s < len(words):
        out.append(_sentence(len(out), words, s, len(words) - 1, duration))
    return out


def _sentence(idx: int, words: list[dict], a: int, b: int, duration: float) -> dict:
    t_last = words[b]["t"]
    nxt = words[b + 1]["t"] if b + 1 < len(words) else duration
    end = t_last + min(0.6, max(0.25, nxt - t_last - 0.05))
    return {
        "i": idx, "a": a, "b": b,
        "text": " ".join(w["w"] for w in words[a:b + 1]),
        "start": words[a]["t"], "end": round(min(end, duration), 3),
    }


def parse_keep(spec: str | list[int], n: int) -> list[int]:
    """'0,6-7,9' -> [0, 6, 7, 9]; 'all' -> every sentence."""
    if isinstance(spec, list):
        keep = sorted(set(int(i) for i in spec))
    elif spec.strip().lower() == "all":
        keep = list(range(n))
    else:
        keep = set()
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                lo, hi = part.split("-", 1)
                keep.update(range(int(lo), int(hi) + 1))
            else:
                keep.add(int(part))
        keep = sorted(keep)
    bad = [i for i in keep if i < 0 or i >= n]
    if bad:
        raise ValueError(f"sentence index out of range: {bad} (0..{n - 1})")
    return keep


def group_runs(keep: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    for i in keep:
        if groups and groups[-1][-1] == i - 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def plan_segments(words: list[dict], sentences: list[dict], groups: list[list[int]], scenes: list[float],
                  env: np.ndarray, sr: int, duration: float, lock_first_scene: bool = True,
                  fps: float = 24.0) -> list[dict]:
    T = [w["t"] for w in words]
    B = list(scenes)

    def snap(t0: float, t1: float) -> float:
        a, b = max(0, int(t0 * sr)), min(len(env), int(t1 * sr))
        if b <= a:
            return t0
        return (a + int(np.argmin(env[a:b]))) / sr

    def first_frag(v0: float) -> float:
        nb = [b for b in B if b > v0 + 0.004]
        return (nb[0] - v0) if nb else 99.0

    def last_frag(ve: float) -> float:
        pb = [b for b in B if b < ve - 0.004]
        return (ve - pb[-1]) if pb else 99.0

    plan: list[dict] = []
    for g in groups:
        a = sentences[g[0]]["a"]
        b = sentences[g[-1]]["b"]
        astart = snap(max(0.0, T[a] - 0.30), max(0.05, T[a] - 0.03)) if T[a] > 0.3 else 0.0
        nxt = T[b + 1] if b + 1 < len(T) else duration
        lastend = T[b] + min(0.55, max(0.2, nxt - T[b] - 0.05))
        if nxt - T[b] > 0.6 or b + 1 >= len(T):
            base_end = snap(min(duration, lastend - 0.05), min(duration, lastend + 0.25))
        else:
            base_end = lastend
        base_end = min(base_end, duration)
        aends = {base_end} | {bb for bb in B if T[b] + 0.30 <= bb <= base_end + 0.12}

        locked = lock_first_scene and (not B or astart < B[0])
        if locked:
            v0s = [astart]          # lip-synced opening scene: keep picture and sound together
        else:
            v0s = [astart + k / fps for k in range(-3, 17)]
            v0s += [bb + 0.01 for bb in B if astart - 0.15 <= bb <= astart + 0.7]

        best = None
        for ae in aends:
            dur = ae - astart
            for v0 in v0s:
                if v0 < 0:
                    continue
                ve = v0 + dur
                over = max(0.0, ve - duration)
                if over > 0.25:
                    continue
                vdur, hold = dur, 0.0
                b2 = [bb for bb in B if ve - 0.2 <= bb <= ve + 0.05 and bb > v0 + 0.8]
                if b2:
                    vdur = b2[0] - FRAME_TAIL_MARGIN - v0
                    hold = dur - vdur
                    lf = 99.0
                else:
                    lf = last_frag(min(ve, duration + 0.001))
                ff = first_frag(v0)
                pen = (12 * max(0.0, MIN_FRAGMENT - ff) + 12 * max(0.0, MIN_FRAGMENT - lf)
                       + 0.8 * abs(v0 - astart) + 0.5 * abs(ae - base_end) + 1.0 * over + 0.6 * hold)
                if best is None or pen < best[0]:
                    best = (pen, ae, v0, dur, vdur)
        _, ae, v0, dur, vdur = best
        near = [bb for bb in B if abs(v0 - bb) < 0.05]
        if near and not locked:
            v0 = max(v0, near[0] + 0.012)
        plan.append({"astart": round(astart, 3), "aend": round(ae, 3), "v0": round(v0, 3),
                     "dur": round(dur, 3), "vdur": round(vdur, 3), "group": g})
    return plan
