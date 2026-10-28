from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import models
from .media import MediaError
from .styles import FONTS, PRESETS, Hook, resolve


def _workdir(video: Path, given: str | None) -> Path:
    return Path(given) if given else Path(".opencaptions") / video.stem


def _progress(stage: str, frac: float) -> None:
    print(f"\r{stage:<11} {frac * 100:5.1f}%", end="" if frac < 1 else "\n", file=sys.stderr, flush=True)


def _print_sentences(data: dict) -> None:
    for s in data["sentences"]:
        print(f"{s['i']:>3}  {s['start']:6.1f} - {s['end']:6.1f}  {s['text']}")
    print(f"\n{len(data['sentences'])} sentences, {data['duration']:.1f}s, {len(data['scenes'])} scene cuts")


def cmd_analyze(a) -> int:
    from .pipeline import analyze

    video = Path(a.video)
    data = analyze(video, _workdir(video, a.workdir), progress=_progress, language=a.language,
                   engine=a.engine, whisper_model=a.whisper_model)
    _print_sentences(data)
    return 0


def cmd_render(a) -> int:
    from .pipeline import analyze, load_analysis, render

    video = Path(a.video)
    wd = _workdir(video, a.workdir)
    if not (wd / "analysis.json").exists():
        analyze(video, wd, progress=_progress, language=a.language, engine=a.engine, whisper_model=a.whisper_model)
    style = resolve(a.style)
    overrides = {k: v for k, v in {"size": a.size, "margin_bottom": a.margin, "accent_color": a.accent_color}.items() if v is not None}
    if overrides:
        style = style.with_overrides(**overrides)
    out = Path(a.out) if a.out else video.with_name(f"{video.stem}_captioned.mp4")
    hook = None
    if a.hook:
        hook = Hook(a.hook, end=a.hook_seconds, top=a.hook_top, size=a.hook_size, box=a.hook_box,
                    color=a.hook_color.lstrip("#"), soft_shadow=a.hook_soft_shadow, pop=a.hook_pop, backdrop=a.hook_backdrop, backdrop_color=a.hook_backdrop_color.lstrip("#"),
                    backdrop_alpha=a.hook_backdrop_alpha, pad_x=a.hook_pad_x, pad_y=a.hook_pad_y, radius=a.hook_radius, bounce=a.hook_bounce, line_height=a.hook_line_height, fade_in=a.hook_fade_in,
                    box_color=a.hook_box_color.lstrip("#"), box_alpha=a.hook_box_alpha, max_lines=a.hook_max_lines, outline=a.hook_outline, outline_color=a.hook_outline_color.lstrip("#"),
                    outline_alpha=a.hook_outline_alpha, shadow=a.hook_shadow, blur=a.hook_blur, font=a.hook_font,
                    small_color=a.hook_small_color.lstrip("#"))
    r = render(video, wd, a.keep, style, out, brand=a.brand or [], fixes=a.fix or [], progress=_progress,
               preset=a.preset, crf=a.crf, hook=hook, clean=not a.keep_metadata)
    print(f"{r['output']}  ({r['duration']:.1f}s, {r['segments']} clip(s))")
    return 0


def cmd_models(a) -> int:
    if a.action == "fetch":
        models.fetch_fonts()
        if not a.skip_english_model:
            models.fetch_model()
    print(models.status())
    return 0


def cmd_styles(a) -> int:
    for name, st in PRESETS.items():
        print(f"{name:<12} font={st.font} size={st.size} caps={st.caps} accent={st.accent}")
    print("\nfonts:", ", ".join(FONTS))
    return 0


def cmd_serve(a) -> int:
    import uvicorn

    uvicorn.run("opencaptions.web.app:app", host=a.host, port=a.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="opencaptions", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("models", help="download or check the speech model and fonts")
    p.add_argument("action", choices=["fetch", "status"])
    p.add_argument("--skip-english-model", action="store_true",
                   help="fonts only, for other languages (Whisper downloads its own model on first use)")
    p.set_defaults(fn=cmd_models)

    p = sub.add_parser("analyze", help="transcribe and detect scene cuts, print numbered sentences")
    p.add_argument("--language", default="en", help="en, de, fr, ... anything Whisper supports")
    p.add_argument("--engine", default="auto", choices=["auto", "parakeet", "whisper"])
    p.add_argument("--whisper-model", default="medium", help="tiny, base, small, medium, large-v3")
    p.add_argument("video")
    p.add_argument("--workdir")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("render", help="cut to the chosen sentences and burn in captions")
    p.add_argument("video")
    p.add_argument("--keep", default="all", help="e.g. 0,6-7,9  or  all")
    p.add_argument("--style", default="plain", help=f"preset: {', '.join(PRESETS)}")
    p.add_argument("--size", type=int)
    p.add_argument("--margin", type=int, help="distance of the captions from the bottom edge (px at 1920 high)")
    p.add_argument("--accent-color", help="RRGGBB")
    p.add_argument("--brand", action="append", help="phrase that must not be split across captions")
    p.add_argument("--fix", action="append", help="word=replacement, e.g. wright=right")
    p.add_argument("--hook", help="text shown near the top for the first seconds, separate from the captions")
    p.add_argument("--hook-seconds", type=float, default=4.2)
    p.add_argument("--hook-top", type=int, default=260, help="px from the top at 1920 high")
    p.add_argument("--hook-size", type=int, default=64)
    p.add_argument("--hook-color", default="FFFFFF", help="RRGGBB, e.g. FFDD00 for yellow")
    p.add_argument("--hook-backdrop", default="", choices=["", "band", "rounded"], help="strip or rounded box behind the hook")
    p.add_argument("--hook-backdrop-color", default="000000")
    p.add_argument("--hook-backdrop-alpha", type=int, default=0, help="0 opaque")
    p.add_argument("--hook-pad-x", type=float, default=40.0)
    p.add_argument("--hook-pad-y", type=float, default=26.0)
    p.add_argument("--hook-radius", type=float, default=26.0)
    p.add_argument("--hook-bounce", action="store_true", help="TikTok style bounce-in")
    p.add_argument("--hook-line-height", type=float, default=0.0, help="0 font default, 1.0 tight")
    p.add_argument("--hook-pop", action="store_true", help="snap in from slightly smaller")
    p.add_argument("--hook-fade-in", type=float, default=0.18, help="seconds, 0 = visible from the first frame")
    p.add_argument("--hook-box-color", default="000000")
    p.add_argument("--hook-box-alpha", type=int, default=140, help="0 opaque box")
    p.add_argument("--hook-max-lines", type=int, default=3)
    p.add_argument("--hook-soft-shadow", type=float, default=0.0, help="0 off, 1 gentle soft drop shadow")
    p.add_argument("--hook-outline", type=float, default=3.0)
    p.add_argument("--hook-outline-color", default="000000", help="RRGGBB, a grey looks softer than black")
    p.add_argument("--hook-outline-alpha", type=int, default=0, help="0 opaque, 255 invisible")
    p.add_argument("--hook-shadow", type=float, default=0.8, help="shadow distance in px at 1920 high")
    p.add_argument("--hook-blur", type=float, default=0.0, help="soften the shadow edge")
    p.add_argument("--hook-font", default="inter-bold", help="font id, e.g. tinos for a Times style serif")
    p.add_argument("--hook-small-color", default="F7EECA", help="first line colour when the hook is split with |")
    p.add_argument("--hook-box", action="store_true", help="dark box behind the hook instead of a soft shadow")
    p.add_argument("--keep-metadata", action="store_true", help="keep source and encoder tags instead of stripping them")
    p.add_argument("--preset", default="veryfast", help="x264 preset (superfast renders faster)")
    p.add_argument("--crf", type=int, default=20)
    p.add_argument("--language", default="en", help="en, de, fr, ... anything Whisper supports")
    p.add_argument("--engine", default="auto", choices=["auto", "parakeet", "whisper"])
    p.add_argument("--whisper-model", default="medium", help="tiny, base, small, medium, large-v3")
    p.add_argument("-o", "--out")
    p.add_argument("--workdir")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("styles", help="list presets and fonts")
    p.set_defaults(fn=cmd_styles)

    p = sub.add_parser("serve", help="start the local web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_serve)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (RuntimeError, ValueError, KeyError, MediaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
