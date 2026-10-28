from pathlib import PureWindowsPath

from opencaptions.captions import chunk_words, norm, stopwords_for
from opencaptions.pipeline import _filter_path
from opencaptions.transcribe import to_latin, whisper_words


def test_cyrillic_to_latin():
    assert to_latin("Добар дан, шта радите? Љубав, њушка, џем, ђак, ћерка, чај") == \
        "Dobar dan, šta radite? Ljubav, njuška, džem, đak, ćerka, čaj"
    assert to_latin("Već latinica: šđčćž") == "Već latinica: šđčćž"
    assert to_latin("ЉУБАВ ЊУШКА Њ") == "LJUBAV NJUŠKA Nj"


def test_whisper_words_merges_punctuation_and_transliterates():
    raw = [(" Тражила", 0.1), (" сам", 0.5), (" кафу", 0.8), (".", 1.2), (" ", 1.3), (" Онда", 2.0)]
    w = whisper_words(raw, "sr")
    assert [x["w"] for x in w] == ["Tražila", "sam", "kafu.", "Onda"]
    assert w[2]["t"] == 0.8


def test_norm_keeps_serbian_letters():
    assert norm("Što,") == "što"
    assert norm("ćerka") == "ćerka"


def test_serbian_captions_do_not_end_on_function_words():
    text = ("Tražila sam kafu u tri kafica i skoro sam odustala od toga da nađem pravi, "
            "a onda mi je drugarica rekla za Acme Coffee koji sve rade ovde u gradu.").split()
    ch = chunk_words(text, max_chars=19, max_words=3, stop=stopwords_for("sr"))
    assert sorted(i for c in ch for i in c) == list(range(len(text)))
    stops = stopwords_for("sr")
    for c in ch[:-1]:
        last = text[c[-1]]
        assert last[-1] in ".?!," or norm(last) not in stops, last


def test_windows_path_is_escaped_for_ffmpeg_filters():
    assert _filter_path(PureWindowsPath("C:\\Users\\User\\AppData\\Local\\opencaptions\\fonts")) == \
        "'C\\:/Users/User/AppData/Local/opencaptions/fonts'"
    assert _filter_path(PureWindowsPath("D:\\my fonts\\it's")) == "'D\\:/my fonts/it'\\''s'"


def test_whisper_model_goes_into_the_opencaptions_data_dir(tmp_path, monkeypatch):
    import sys
    import types

    seen = {}

    class FakeModel:
        def __init__(self, size, **kw):
            seen["size"], seen["kw"] = size, kw

        def transcribe(self, *a, **k):
            return iter([]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setenv("OPENCAPTIONS_HOME", str(tmp_path))
    from opencaptions.transcribe import transcribe_whisper

    assert transcribe_whisper("x.wav", 10.0, "sr", "small") == []
    assert seen["kw"]["download_root"] == str(tmp_path / "models" / "whisper")


def test_inter_archive_layout_is_recognised(tmp_path):
    import io
    import zipfile

    from opencaptions.models import extract_inter

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("extras/ttf/Inter-SemiBold.ttf", b"a")
        z.writestr("extras/ttf/Inter-Bold.ttf", b"b")
        z.writestr("extras/otf/Inter-Bold.otf", b"c")
        z.writestr("web/Inter-Bold.woff2", b"d")
    got = extract_inter(buf.getvalue(), tmp_path)
    assert sorted(got) == ["Inter-Bold.ttf", "Inter-SemiBold.ttf"]
    assert (tmp_path / "Inter-Bold.ttf").read_bytes() == b"b"


def test_missing_font_is_an_error_not_a_silent_fallback(tmp_path, monkeypatch):
    import pytest

    from opencaptions.captions import build_ass
    from opencaptions.styles import resolve

    monkeypatch.setenv("OPENCAPTIONS_HOME", str(tmp_path))
    with pytest.raises(RuntimeError, match="models fetch"):
        build_ass(["hello", "world"], [0.1, 0.5], 2.0, resolve("plain"), 1080, 1920)
