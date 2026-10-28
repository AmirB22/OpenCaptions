"""Turn timed words into an ASS subtitle file."""
from __future__ import annotations

import functools
import itertools
import math
import re
import struct
from pathlib import Path

from PIL import ImageFont

from . import paths
from .styles import FONTS, Hook, Style

STOP_EN = {"a", "an", "the", "and", "i", "to", "of", "in", "on", "at", "my", "for", "that", "with", "or",
           "but", "so", "then", "than", "when", "is", "it", "as", "if", "me", "they", "their", "be", "was",
           "up", "out"}
# function words a caption should not end on
STOP_SR = {"i", "u", "na", "je", "se", "da", "za", "sa", "s", "od", "do", "a", "ali", "pa", "ili", "što", "sto",
           "kao", "to", "ta", "taj", "te", "ti", "mi", "me", "ja", "on", "ona", "ono", "oni", "su", "sam", "smo",
           "ste", "bi", "će", "ce", "li", "ni", "iz", "po", "o", "bez", "kod", "ko", "šta", "sta", "kad", "kada",
           "gde", "gdje", "kako", "jer", "ako", "već", "vec", "još", "jos", "ne", "nije", "nisam", "moj", "moja",
           "moje", "svoj", "naš", "vaš", "ovo", "ovaj", "ova", "koji", "koja", "koje", "tu", "te", "nam", "vam"}
STOP = STOP_EN


def stopwords_for(language: str) -> set[str]:
    return STOP_SR if language.lower()[:2] in ("sr", "hr", "bs") else STOP_EN
LEAD = 0.04   # captions appear this much before the word


@functools.lru_cache(maxsize=16)
def win_metrics(path: str) -> tuple[int, int, int]:
    """(unitsPerEm, usWinAscent, usWinDescent) of a TrueType font. libass sizes text so that
    winAscent + winDescent equals the requested font size, so this decides how big letters really are."""
    data = Path(path).read_bytes()
    n = struct.unpack(">H", data[4:6])[0]
    tabs = {}
    for i in range(n):
        tag, _cs, off, ln = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
        tabs[tag.decode("latin-1")] = (off, ln)
    upem = struct.unpack(">H", data[tabs["head"][0] + 18: tabs["head"][0] + 20])[0]
    o = tabs["OS/2"][0]
    win_a, win_d = struct.unpack(">HH", data[o + 74: o + 78])
    return upem, win_a, win_d


def norm(s: str) -> str:
    return re.sub(r"[^\w']", "", s.lower())


def chunk_words(words: list[str], max_chars: int, max_words: int = 3, comma_min: int = 6,
                keep_together: list[list[str]] | None = None, stop: set[str] | None = None) -> list[list[int]]:
    STOP = stop if stop is not None else STOP_EN
    n = len(words)

    def txt(c: list[int]) -> str:
        return " ".join(words[k] for k in c)

    def ends_sentence(w: str) -> bool:
        w = w.rstrip("\"')")
        return bool(w) and w[-1] in ".?!"

    ch: list[list[int]] = []
    cur: list[int] = []
    for i, x in enumerate(words):
        cur.append(i)
        if ends_sentence(x):
            ch.append(cur)
            cur = []
            continue
        if x.endswith(",") and len(txt(cur)) >= comma_min:
            ch.append(cur)
            cur = []
            continue
        if i + 1 < n and (len(txt(cur)) + 1 + len(words[i + 1]) > max_chars or len(cur) >= max_words):
            carry: list[int] = []
            while len(cur) > 1 and norm(words[cur[-1]]) in STOP and len(carry) < 3:
                carry.insert(0, cur.pop())
            ch.append(cur)
            cur = carry
    if cur:
        ch.append(cur)

    soft_end = lambda w: w[-1] not in ".?!,"
    for k in range(1, len(ch)):
        while len(ch[k]) < 2 and len(ch[k - 1]) >= 4 and soft_end(words[ch[k - 1][-1]]):
            ch[k].insert(0, ch[k - 1].pop())
        while len(ch[k - 1]) > 1 and norm(words[ch[k - 1][-1]]) in STOP and soft_end(words[ch[k - 1][-1]]):
            ch[k].insert(0, ch[k - 1].pop())
    k = len(ch) - 1
    while k >= 0:
        if len(ch[k]) == 1:
            w = words[ch[k][0]]
            if norm(w) in STOP and k + 1 < len(ch) and soft_end(w) and len(txt(ch[k] + ch[k + 1])) <= max_chars + 7:
                ch[k + 1] = ch[k] + ch[k + 1]
                ch.pop(k)
            elif k > 0 and soft_end(words[ch[k - 1][-1]]) and len(txt(ch[k - 1] + ch[k])) <= max_chars + 7:
                ch[k - 1] += ch[k]
                ch.pop(k)
        k -= 1
    ch = [c for c in ch if c]

    for ph in keep_together or []:
        nw = [norm(w) for w in words]
        L = len(ph)
        for i in range(n - L + 1):
            if nw[i:i + L] == ph:
                where = [next(k for k, c in enumerate(ch) if j in c) for j in range(i, i + L)]
                if len(set(where)) > 1:
                    tgt = where[-1]
                    for j in range(i, i + L):
                        for c in ch:
                            if j in c and c is not ch[tgt]:
                                c.remove(j)
                    ch[tgt] = sorted(set(ch[tgt]) | set(range(i, i + L)))
                    ch = [c for c in ch if c]
    return ch


def chunk_times(ch: list[list[int]], T: list[float], W: list[str], duration: float) -> list[tuple[float, float]]:
    out = []
    for n, c in enumerate(ch):
        st = max(0.0, T[c[0]] - LEAD)
        est = T[c[-1]] + min(0.9, 0.28 + 0.055 * len(W[c[-1]]))
        if n + 1 < len(ch):
            nx = T[ch[n + 1][0]] - LEAD
            en = nx if nx - est < 0.35 else est
            en = min(en, nx)
        else:
            en = min(duration, est + 0.2)
        out.append((st, max(en, st + 0.05)))
    return out


def _ts(s: float) -> str:
    s = max(0.0, s)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def _clean(w: str) -> str:
    return w.replace('"', "").rstrip(",.?!")


def _require_font(fpath: Path) -> None:
    if not fpath.exists():
        raise RuntimeError(f"font file missing: {fpath.name} (expected in {fpath.parent}). "
                           "Run: opencaptions models fetch")


def _hook_events(hook: Hook, width: int, height: int) -> tuple[list[str], str]:
    scale = height / 1920.0
    font = FONTS[hook.font]
    size = max(8, round(hook.size * scale))
    fpath = paths.fonts_dir() / font.filename
    _require_font(fpath)
    pil = ImageFont.truetype(str(fpath), size) if fpath.exists() else None
    wid = lambda t: (pil.getlength(t) if pil else len(t) * size * 0.58)
    max_w = hook.max_width * scale
    if "|" in hook.text:
        return _tiered_hook(hook, width, height, font, pil_for=lambda sz: ImageFont.truetype(str(fpath), sz)
                            if fpath.exists() else None)
    words = hook.text.split()
    n_lines = min(hook.max_lines, len(words), max(1, math.ceil(wid(" ".join(words)) / max_w)))
    lines = [" ".join(words)]
    if n_lines > 1:                       # split into the fewest lines, as even as possible
        best = None
        for cuts in itertools.combinations(range(1, len(words)), n_lines - 1):
            bounds = (0, *cuts, len(words))
            parts = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
            widest_part = max(wid(x) for x in parts)
            if best is None or widest_part < best[0]:
                best = (widest_part, parts)
        lines = best[1]
    if "//" in hook.text:
        lines = [part.strip() for part in hook.text.split("//") if part.strip()]
    widest = max(wid(l) for l in lines)
    # libass sizes text by winAscent+winDescent, so letters are smaller than a PIL font of the same size
    if fpath.exists():
        upem, wa, wd = win_metrics(str(fpath))
        factor = (wa + wd) / upem
    else:
        factor = 1.2
    rendered = widest / factor
    fs = size if rendered <= max_w else max(8, int(size * max_w / rendered))
    x = width // 2
    y0 = round(hook.top * scale)
    if hook.line_height > 0:              # tight, explicit line spacing: one event per line
        pitch = fs * hook.line_height
        rows = [(ln, y0 + round(i * pitch)) for i, ln in enumerate(lines)]
    else:
        rows = [("\\N".join(lines), y0)]
    fade = f"\\fad({int(hook.fade_in * 1000)},250)"
    if hook.bounce:
        fade += "\\fscx80\\fscy80\\t(0,110,\\fscx108\\fscy108)\\t(110,210,\\fscx100\\fscy100)"
    elif hook.pop:
        fade += "\\fscx86\\fscy86\\t(0,140,\\fscx100\\fscy100)"
    ev = []
    if hook.backdrop and fpath.exists():
        ev.append(_backdrop_event(hook, lines, fs, y0, width, scale, fpath))
    blur = f"\\blur{hook.blur}" if hook.blur else ""
    for text, y in rows:
        pos = f"\\an8\\pos({x},{y})"
        if not hook.box and hook.glow > 0:
            ev.append(f"Dialogue: 2,{_ts(hook.start)},{_ts(hook.end)},Hook,,0,0,0,,"
                      f"{{{pos}\\fs{fs}\\1a&HFF&\\3a&H70&\\3c&H000000&\\bord{12 * hook.glow:.1f}\\blur{12 * hook.glow:.1f}\\shad0{fade}}}{text}")
        if hook.soft_shadow > 0 and not hook.box:
            k = hook.soft_shadow
            sy = y + round(3 * k * scale)
            alpha = int(255 - min(1.0, k) * 140)
            ev.append(f"Dialogue: 2,{_ts(hook.start)},{_ts(hook.end)},Hook,,0,0,0,,"
                      f"{{\\an8\\pos({x},{sy})\\fs{fs}\\1c&H000000&\\1a&H{alpha:02X}&\\3a&HFF&\\4a&HFF&\\bord0\\shad0"
                      f"\\blur{4 * k:.1f}{fade}}}{text}")
        ev.append(f"Dialogue: 3,{_ts(hook.start)},{_ts(hook.end)},{'HookBox' if hook.box else 'Hook'},,0,0,0,,"
                  f"{{{pos}\\fs{fs}{blur}{fade}}}{text}")
    f = font
    c = hook.color
    primary = f"&H00{c[4:6]}{c[2:4]}{c[0:2]}"
    bc = hook.box_color
    box_c = f"&H{hook.box_alpha:02X}{bc[4:6]}{bc[2:4]}{bc[0:2]}"
    oc = hook.outline_color
    outline_c = f"&H{hook.outline_alpha:02X}{oc[4:6]}{oc[2:4]}{oc[0:2]}"
    st = (f"Style: Hook,{f.ass_name},{size},{primary},&H000000FF,{outline_c},&H{hook.shadow_alpha:02X}000000,{f.bold},0,0,0,100,100,0.3,0,1,"
          f"{hook.outline * scale:.2f},{hook.shadow * scale:.2f},8,70,70,0,1\n"
          f"Style: HookBox,{f.ass_name},{size},{primary},&H000000FF,{box_c},{box_c},{f.bold},0,0,0,100,100,0.3,0,3,"
          f"{18 * scale:.2f},0,8,70,70,0,1\n")
    return ev, st


def _rrect(w: float, h: float, r: float) -> str:
    r = max(0.0, min(r, w / 2, h / 2))
    f = lambda v: f"{v:.1f}"
    if r < 0.5:
        return f"m 0 0 l {f(w)} 0 l {f(w)} {f(h)} l 0 {f(h)}"
    k = 0.5523 * r
    return (f"m {f(r)} 0 l {f(w - r)} 0 b {f(w - r + k)} 0 {f(w)} {f(r - k)} {f(w)} {f(r)} "
            f"l {f(w)} {f(h - r)} b {f(w)} {f(h - r + k)} {f(w - r + k)} {f(h)} {f(w - r)} {f(h)} "
            f"l {f(r)} {f(h)} b {f(r - k)} {f(h)} 0 {f(h - r + k)} 0 {f(h - r)} "
            f"l 0 {f(r)} b 0 {f(r - k)} {f(r - k)} 0 {f(r)} 0")


def _backdrop_event(hook: Hook, lines: list[str], fs: int, y0: int, width: int, scale: float, fpath) -> str:
    """A full-width strip or one rounded box behind the text lines, drawn as an ASS vector shape."""
    upem, wa, wd = win_metrics(str(fpath))
    em = max(8, round(fs * upem / (wa + wd)))
    pf = ImageFont.truetype(str(fpath), em)
    bb = pf.getbbox("H")
    baseline = fs * wa / (wa + wd)
    cap_top, cap_bot = baseline - (bb[3] - bb[1]), baseline
    widest = max(pf.getlength(l) for l in lines)
    pitch = fs * (hook.line_height or 1.0)
    padx, pady, rad = hook.pad_x * scale, hook.pad_y * scale, hook.radius * scale
    top = y0 + cap_top - pady
    bottom = y0 + (len(lines) - 1) * pitch + cap_bot + pady
    if hook.backdrop == "band":
        x0, bw, rad = 0.0, float(width), 0.0
    else:
        bw = widest + 2 * padx
        x0 = (width - bw) / 2
    c = hook.backdrop_color
    bgr = f"{c[4:6]}{c[2:4]}{c[0:2]}"
    return (f"Dialogue: 1,{_ts(hook.start)},{_ts(hook.end)},Hook,,0,0,0,,"
            f"{{\\an7\\pos({x0:.1f},{top:.1f})\\1c&H{bgr}&\\1a&H{hook.backdrop_alpha:02X}&\\3a&HFF&\\4a&HFF&"
            f"\\bord0\\shad0\\fad({int(hook.fade_in * 1000)},250)\\p1}}{_rrect(bw, bottom - top, rad)}{{\\p0}}")


def _tiered_hook(hook: Hook, width: int, height: int, font, pil_for) -> tuple[list[str], str]:
    """'where I found my|BEST|COFFEE IN TOWN': small first line, large second line, medium rest."""
    scale = height / 1920.0
    parts = [p.strip() for p in hook.text.split("|") if p.strip()]
    base = hook.size * scale
    sizes = [base * hook.small_ratio] + [base] + [base * hook.mid_ratio] * max(0, len(parts) - 2)
    sizes = [max(8, round(x)) for x in sizes[:len(parts)]] if len(parts) > 1 else [round(base)]
    max_w = hook.max_width * scale

    def wid(t: str, sz: int) -> float:
        f = pil_for(sz)
        return f.getlength(t) if f else len(t) * sz * 0.5

    widest = max(wid(t, sz) for t, sz in zip(parts, sizes))
    k = min(1.0, max_w / widest) if widest else 1.0
    sizes = [max(8, int(sz * k)) for sz in sizes]

    def bgr(c: str) -> str:
        return f"&H00{c[4:6]}{c[2:4]}{c[0:2]}&"

    colors = [hook.small_color] + [hook.color] * (len(parts) - 1) if len(parts) > 1 else [hook.color]
    text = "\\N".join(f"{{\\fs{sz}\\c{bgr(c)}}}{t}" for t, sz, c in zip(parts, sizes, colors))
    pos = f"\\an8\\pos({width // 2},{round(hook.top * scale)})"
    ev = [f"Dialogue: 3,{_ts(hook.start)},{_ts(hook.end)},Hook,,0,0,0,,{{{pos}\\fad(180,250)}}{text}"]
    f = font
    st = (f"Style: Hook,{f.ass_name},{sizes[0]},&H00FFFFFF,&H000000FF,&H00000000,&H70000000,{f.bold},0,0,0,100,100,0.3,0,1,"
          f"{hook.outline * scale:.2f},{hook.shadow * scale:.2f},8,70,70,0,1\n")
    return ev, st


def build_ass(words: list[str], times: list[float], duration: float, style: Style, width: int, height: int,
              keep_together: list[list[str]] | None = None, hook: Hook | None = None,
              language: str = "en") -> str:
    font = FONTS[style.font]
    scale = height / 1920.0
    size = max(8, round(style.size * scale))
    outline, shadow = style.outline * scale, style.shadow * scale
    max_w = style.max_width * scale * (width / 1080.0 if width < 1080 else 1.0)
    y = height - round(style.margin_bottom * scale)
    fpath = paths.fonts_dir() / font.filename
    _require_font(fpath)
    pil = ImageFont.truetype(str(fpath), size) if fpath.exists() else None

    def text_w(s: str) -> float:
        if pil is None:
            return len(s) * size * 0.58
        return pil.getlength(s) + style.spacing * len(s) + outline * 2

    ch = chunk_words(words, style.max_chars, style.max_words, keep_together=keep_together,
                     stop=stopwords_for(language))
    tm = chunk_times(ch, times, words, duration)
    acc = style.accent_color
    bgr = acc[4:6] + acc[2:4] + acc[0:2]
    ACC = "{\\c&H00" + bgr + "&}"
    WHT = "{\\c&HFFFFFF&}"
    events: list[str] = []
    for c, (cst, cen) in zip(ch, tm):
        ws = [_clean(words[k]) for k in c]
        if style.caps:
            ws = [w.upper() for w in ws]
        full = " ".join(ws)
        fs = size
        if text_w(full) > max_w:
            fs = max(8, int(size * max_w / text_w(full)))
        base = f"\\an2\\pos({width // 2},{y})\\fs{fs}"
        if not style.accent:
            pop = "\\fscx94\\fscy94\\t(0,90,\\fscx100\\fscy100)" if style.pop else ""
            events.append(f"Dialogue: 0,{_ts(cst)},{_ts(cen)},Cap,,0,0,0,,{{{base}{pop}}}{full}")
            continue
        for j, k in enumerate(c):
            st = cst if j == 0 else times[k] - LEAD
            en = cen if j + 1 == len(c) else times[c[j + 1]] - LEAD
            en = min(en, cen)
            if en - st < 0.04:
                continue
            parts = [(ACC if q == j else WHT) + ws[q] for q in range(len(ws))]
            pop = "\\fscx92\\fscy92\\t(0,80,\\fscx100\\fscy100)" if (j == 0 and style.pop) else ""
            events.append(f"Dialogue: 0,{_ts(st)},{_ts(en)},Cap,,0,0,0,,{{{base}{pop}}}" + " ".join(parts))

    hook_styles = ""
    if hook is not None:
        hev, hook_styles = _hook_events(hook, width, height)
        events = hev + events
    margin_v = round(style.margin_bottom * scale)
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{font.ass_name},{size},&H00FFFFFF,&H000000FF,&H00000000,&H70000000,{font.bold},0,0,0,"
        f"100,100,{style.spacing},0,1,{outline:.2f},{shadow:.2f},2,70,70,{margin_v},1\n"
        f"{hook_styles}\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    return header + "\n".join(events) + "\n"
