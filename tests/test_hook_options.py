import pytest

from opencaptions.styles import hook_from_options


def test_no_text_means_no_hook():
    assert hook_from_options(None) is None
    assert hook_from_options({"text": "  \n "}) is None


def test_newlines_become_explicit_line_breaks():
    h = hook_from_options({"text": "WHERE I FOUND MY\nFAVORITE SHOP"})
    assert h.text == "WHERE I FOUND MY // FAVORITE SHOP"


def test_box_look_sets_rounded_backdrop():
    h = hook_from_options({"text": "Hi", "look": "box", "color": "#FFD400", "box_color": "111111", "seconds": 4.3})
    assert (h.backdrop, h.backdrop_color, h.color, h.end) == ("rounded", "111111", "FFD400", 4.3)
    assert h.fade_in == 0 and h.line_height == 0.8


def test_outline_look_has_no_backdrop():
    assert hook_from_options({"text": "Hi"}).backdrop == ""


def test_bad_values_are_rejected():
    with pytest.raises(ValueError):
        hook_from_options({"text": "Hi", "look": "neon"})
    with pytest.raises(ValueError):
        hook_from_options({"text": "Hi", "font": "comic"})
