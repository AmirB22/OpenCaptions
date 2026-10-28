"""Caption styles. All sizes are defined for a 1080x1920 frame and scaled to the actual video."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class Font:
    ass_name: str     # family name as libass sees it
    filename: str
    bold: int = 0
    label: str = ""


FONTS: dict[str, Font] = {
    "inter-semibold": Font("Inter SemiBold", "Inter-SemiBold.ttf", 0, "Inter SemiBold"),
    "inter-bold": Font("Inter", "Inter-Bold.ttf", 1, "Inter Bold"),
    "montserrat-semibold": Font("Montserrat SemiBold", "Montserrat-SemiBold.ttf", 0, "Montserrat SemiBold"),
    "montserrat-bold": Font("Montserrat", "Montserrat-Bold.ttf", 1, "Montserrat Bold"),
    "montserrat-extrabold": Font("Montserrat ExtraBold", "Montserrat-ExtraBold.ttf", 0, "Montserrat ExtraBold"),
    "bebas-neue": Font("Bebas Neue", "BebasNeue-Regular.ttf", 0, "Bebas Neue"),
    "tinos": Font("Tinos", "Tinos-Regular.ttf", 0, "Tinos (Times style serif)"),
}


@dataclass(frozen=True)
class Style:
    font: str = "inter-semibold"
    size: int = 70
    caps: bool = False
    outline: float = 4.0
    shadow: float = 1.5
    spacing: float = 0.4
    accent: bool = False
    accent_color: str = "8FB04A"
    margin_bottom: int = 560   # px from the bottom edge, at 1920 high
    max_chars: int = 19
    max_words: int = 3
    max_width: int = 940
    pop: bool = True

    def with_overrides(self, **kw) -> "Style":
        valid = {f.name for f in fields(self)}
        clean = {k: v for k, v in kw.items() if k in valid and v is not None}
        return Style(**{**asdict(self), **clean})


@dataclass(frozen=True)
class Hook:
    """Hook text near the top of the frame."""
    text: str
    start: float = 0.0
    end: float = 3.8
    size: int = 68
    top: int = 300   # px from the top edge, at 1920 high
    font: str = "inter-bold"
    box: bool = False
    outline: float = 3.0
    shadow: float = 0.8
    glow: float = 0.0
    max_width: int = 900
    color: str = "FFFFFF"
    max_lines: int = 3
    small_color: str = "F7EECA"
    backdrop: str = ""
    backdrop_color: str = "000000"
    backdrop_alpha: int = 0   # alphas: 0 is opaque, 255 invisible
    pad_x: float = 40.0
    pad_y: float = 26.0
    radius: float = 26.0
    line_height: float = 0.0   # 0 = font default, 1.0 = lines one font size apart
    bounce: bool = False
    pop: bool = False
    fade_in: float = 0.18
    box_color: str = "000000"
    box_alpha: int = 140
    soft_shadow: float = 0.0
    outline_color: str = "000000"
    outline_alpha: int = 0
    blur: float = 0.0
    shadow_alpha: int = 112
    small_ratio: float = 0.5
    mid_ratio: float = 0.6


PRESETS: dict[str, Style] = {
    "plain": Style(),
    "accent": Style(accent=True, max_chars=17),
    "caps-accent": Style(font="inter-semibold", size=78, caps=True, outline=4.5, accent=True, max_chars=15),
    "heavy-caps": Style(font="montserrat-extrabold", size=88, caps=True, outline=7, shadow=0,
                        spacing=1, accent=True, max_chars=15),
    "condensed": Style(font="bebas-neue", size=112, caps=True, outline=5, spacing=1.5,
                       accent=True, max_chars=20),
}


def resolve(name_or_overrides: str | dict | None) -> Style:
    if name_or_overrides is None:
        return PRESETS["plain"]
    if isinstance(name_or_overrides, str):
        if name_or_overrides not in PRESETS:
            raise KeyError(f"unknown style '{name_or_overrides}', available: {', '.join(PRESETS)}")
        return PRESETS[name_or_overrides]
    d = dict(name_or_overrides)
    preset = d.pop("preset", "plain")
    if preset not in PRESETS:
        raise KeyError(f"unknown style '{preset}', available: {', '.join(PRESETS)}")
    base = PRESETS[preset]
    return base.with_overrides(**d)


HOOK_LOOKS = ("outline", "box", "band")


def hook_from_options(o: dict | None) -> Hook | None:
    """Build a Hook from the few options the web UI offers. No text means no hook."""
    o = o or {}
    text = " // ".join(line.strip() for line in str(o.get("text", "")).splitlines() if line.strip())
    if not text:
        return None
    look = o.get("look", "outline")
    if look not in HOOK_LOOKS:
        raise ValueError(f"unknown hook look '{look}', available: {', '.join(HOOK_LOOKS)}")
    font = o.get("font", "inter-bold")
    if font not in FONTS:
        raise ValueError(f"unknown font '{font}'")
    hex6 = lambda v, d: v.lstrip("#") if isinstance(v, str) and len(v.lstrip("#")) == 6 else d
    kw = dict(end=float(o.get("seconds", 4.2)), size=int(o.get("size", 90)), top=int(o.get("top", 200)),
              font=font, color=hex6(o.get("color"), "FFFFFF"))
    if look != "outline":
        kw.update(backdrop="rounded" if look == "box" else "band", backdrop_color=hex6(o.get("box_color"), "000000"),
                  line_height=0.8, fade_in=0.0, shadow=0.0, outline=0.0, max_lines=2)
    return Hook(text, **kw)
