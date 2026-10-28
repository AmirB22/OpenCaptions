from opencaptions.languages import is_supported, language_options


def test_language_options_start_with_english():
    opts = language_options()
    assert opts[0]["id"] == "en"
    assert [o["label"] for o in opts[1:]] == sorted(o["label"] for o in opts[1:])
    assert len({o["id"] for o in opts}) == len(opts)
    assert opts[0]["engine"] == "parakeet" and opts[1]["engine"] == "whisper"


def test_is_supported():
    assert is_supported("EN") and is_supported("de") and is_supported(" sr ")
    assert not is_supported("xx") and not is_supported("")
