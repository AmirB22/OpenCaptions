import numpy as np
import pytest

from opencaptions.captions import chunk_words, norm, STOP
from opencaptions.pipeline import apply_edits, apply_fixes
from opencaptions.plan import group_runs, parse_keep, plan_segments, split_sentences
from opencaptions.styles import resolve


def words_from(text: str, step: float = 0.35, start: float = 0.5) -> list[dict]:
    return [{"w": w, "t": round(start + i * step, 3)} for i, w in enumerate(text.split())]


def test_parse_keep():
    assert parse_keep("0,2-3", 5) == [0, 2, 3]
    assert parse_keep("all", 3) == [0, 1, 2]
    assert parse_keep([3, 1, 1], 5) == [1, 3]
    with pytest.raises(ValueError):
        parse_keep("7", 5)


def test_group_runs():
    assert group_runs([0, 2, 3, 5]) == [[0], [2, 3], [5]]


def test_split_sentences():
    w = words_from("Hello there. How are you? Fine thanks")
    s = split_sentences(w, 10.0)
    assert [x["text"] for x in s] == ["Hello there.", "How are you?", "Fine thanks"]
    assert s[0]["start"] == w[0]["t"]


def test_chunks_do_not_end_on_function_words():
    text = ("I almost gave up on finding the right place and then a friend mentioned "
            "Acme Coffee because they make everything right here in their own shop.").split()
    ch = chunk_words(text, max_chars=19, max_words=3)
    assert sorted(i for c in ch for i in c) == list(range(len(text)))
    for c in ch[:-1]:
        last = text[c[-1]]
        assert last[-1] in ".?!," or norm(last) not in STOP, text[c[-1]]


def test_keep_together():
    text = "then a friend mentioned Acme Coffee and it was great.".split()
    ch = chunk_words(text, max_chars=14, max_words=3, keep_together=[["acme", "coffee"]])
    for c in ch:
        assert (4 in c) == (5 in c)


def test_apply_fixes_keeps_punctuation():
    out = apply_fixes([{"w": "wright,", "t": 1.0}, {"w": "Wright", "t": 2.0}, {"w": "other", "t": 3.0}], ["wright=right"])
    assert [w["w"] for w in out] == ["right,", "right", "other"]


def test_style_resolve():
    assert resolve("plain").accent is False
    assert resolve({"preset": "accent", "size": 60}).size == 60
    with pytest.raises(KeyError):
        resolve({"preset": "nope"})


def test_plan_has_no_scene_slivers():
    text = ("one two three four. five six seven eight nine. ten eleven twelve. "
            "thirteen fourteen fifteen sixteen. seventeen eighteen nineteen.")
    w = words_from(text, step=0.4, start=0.2)
    sents = split_sentences(w, 20.0)
    scenes = [s["start"] + 0.12 for s in sents[1:]] + [s["start"] + 2.1 for s in sents[1:]]
    scenes = sorted(scenes)
    sr = 16000
    env = np.full(int(20.0 * sr), 0.01, dtype=np.float32)
    plan = plan_segments(w, sents, [[0], [2], [4]], scenes, env, sr, 20.0, lock_first_scene=False)
    for p in plan:
        v0, ve = p["v0"], p["v0"] + p["vdur"]
        inside = [b for b in scenes if v0 + 0.05 < b < ve - 0.05]
        before_start = [b for b in scenes if v0 - 0.0417 <= b <= v0 + 0.0417]
        first = min([b - v0 for b in scenes if b > v0 + 0.004] or [99])
        last = min([ve - b for b in scenes if b < ve - 0.004] or [99])
        assert first >= 0.4 or first < 0.0417, (p, first)
        assert last >= 0.4, (p, last)


def test_apply_edits_by_index_keeps_punctuation():
    words = [{"w": "sewn,", "t": 1.0}, {"w": "this", "t": 2.0}, {"w": "place.", "t": 3.0}]
    out = apply_edits(words, {0: "stone", 2: "  band  ", 1: "  "})
    assert [w["w"] for w in out] == ["stone,", "this", "band."]
    assert words[0]["w"] == "sewn,"
    assert apply_edits(words, {}) is words
