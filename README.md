# OpenCaptions

Built this so I don't have to pay for a tool to add captions. Feel free to use it.

Cut a talking video down to the sentences you pick, add a hook text on top, and burn in captions.
Everything runs locally with ffmpeg and a speech model. No account, no watermark, no API keys, nothing
leaves your machine. There is a command line tool and a local web UI.

What it does:

- transcribes the audio with word timings (English with Parakeet, about 100 other languages with Whisper)
- finds the hard cuts in the picture
- cuts on quiet points between sentences, and places the picture cuts on scene boundaries so no
  one or two frame flashes of a neighbouring scene show up at the joins
- builds the captions from the word timings, with an optional hook text at the top, and burns them in

## Install on Linux

```sh
# Arch: sudo pacman -S --needed ffmpeg python
# Debian/Ubuntu: sudo apt install ffmpeg python3-venv
python -m venv .venv
source .venv/bin/activate
pip install -e '.[whisper]'      # drop [whisper] if you only need English
opencaptions models fetch        # English speech model (about 480 MB) and fonts
```

ffmpeg must be built with libass (the usual Linux packages are).

`sherpa-onnx` ships prebuilt wheels for the common Python versions. If pip tries to compile it on a
very new Python, use an older interpreter for the venv, for example with uv:
`uv venv --python 3.12 && source .venv/bin/activate && uv pip install -e '.[whisper]'`

## Install on Windows (PowerShell)

1. Python 3.12 from python.org (tick "Add python.exe to PATH") or `winget install Python.Python.3.12`.
2. ffmpeg: `winget install Gyan.FFmpeg`, then open a new PowerShell window. The Gyan build includes
   libass. Check with `ffmpeg -version`.
3. In the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[whisper]"
opencaptions models fetch
```

If PowerShell refuses to run `Activate.ps1`, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Data (models, fonts, jobs) goes to `%LOCALAPPDATA%\opencaptions`. Set `OPENCAPTIONS_HOME` to change it.
Git for Windows or WSL are not needed.

## Another drive

Everything big (speech models, fonts, uploaded videos, results) lives in one data directory.
Point it at a drive with space before the first download:

```powershell
setx OPENCAPTIONS_HOME "G:\opencaptions-data"     # Windows, applies to new terminals
```

```sh
export OPENCAPTIONS_HOME=/mnt/g/opencaptions-data  # Linux, put in ~/.bashrc to keep it
```

Open a new terminal, then `opencaptions models fetch`. The Whisper model goes into the same
folder. Put the project and its `.venv` on that drive too if C is short on space. Use a local drive
(internal or USB SSD). A cloud-synced or network drive makes video work slow and can break file locks.
Roughly: 0.5 GB English model, 1.5 GB Whisper medium, about 1 GB for the venv, plus a copy of each video.

## Other languages

Add `--language` with a Whisper language code (`de`, `fr`, `es`, `sr`, ...). Anything except English uses
Whisper through faster-whisper, because the English model is English only. The web UI lists all of them.

```sh
opencaptions models fetch --skip-english-model   # fonts only
opencaptions analyze video.mp4 --language de     # first run downloads the Whisper model
opencaptions render video.mp4 --language de --keep all --style plain -o out.mp4
```

- The default model is `medium` (about 1.5 GB, a minute of video takes roughly one to two minutes on
  a CPU). `--whisper-model small` is faster and less accurate, `large-v3` is the most accurate and
  needs a GPU to be comfortable. With an NVIDIA GPU set `OPENCAPTIONS_DEVICE=cuda`.
- The first run needs internet to download the model, after that it works offline.
- Whisper timings are a bit less tight than Parakeet's for English. Check the first few captions and
  use `--fix wrong=right` for words it gets wrong.
- Captions avoid ending a line on short function words for English and for Serbian, Croatian and
  Bosnian. Other languages get the English list, so a line can end on a short word.
- Serbian, Croatian and Bosnian Cyrillic output is converted to Latin script.
- The fonts have Latin and Cyrillic glyphs only. Chinese, Japanese, Korean, Arabic, Hebrew, Thai and
  similar scripts need a font with those glyphs.
- Only tried on a few languages. Test on one clip before relying on it.

## Web UI

```sh
opencaptions serve             # http://127.0.0.1:8765
```

1. Drop a video on the page (or click the box) and pick the language.
2. When the transcript is ready, tick the sentences to keep. Click a word to change it, for example to
   fix a name the speech model got wrong. Changed words are highlighted.
3. Pick a caption style and, if you want one, a hook text with a look (outline, rounded box or band).
4. Render. Results stay in the data directory and can be downloaded from the page.

The server only listens on localhost by default.

## Command line

```sh
opencaptions analyze video.mp4                      # prints numbered sentences with times
opencaptions render video.mp4 --keep 0,6-7,9-10,14,17 --style plain \
    --brand "Acme Coffee" --fix wright=right -o ad.mp4
opencaptions render video.mp4 --keep all --style accent   # captions only, no cuts
opencaptions render video.mp4 --keep all --hook "Looking for good coffee?"
opencaptions styles                                 # presets and fonts
```

Options for `render`: `--size`, `--margin` (distance from the bottom edge in px at 1920 high),
`--accent-color RRGGBB`, `--brand` (phrase never split across two captions), `--fix word=replacement`,
`--language`, `--preset superfast` (faster render), `--crf`.

Hook text: `--hook "text"`, `--hook-seconds`, `--hook-top`, `--hook-size`, `--hook-font`, `--hook-color`,
`--hook-backdrop rounded` and more (see `opencaptions render --help`). `//` in the text is a line break.
It sits near the top for the first seconds, separate from the captions, just under the area Instagram
covers with its own interface.

Analysis is cached in `.opencaptions/<name>/`, so rendering variants after the first run is quick.

## Hook A/B example

```sh
scripts/hook_example.sh /path/to/video.mp4 out
```

Analyses the video once and renders two hook versions (text A and text B, black rounded box, yellow
text) on the full video with white captions. Copy the script and change the texts and colours.

## Styles

Presets live in `opencaptions/styles.py`: `plain` (white sentence case), `accent` (same, spoken word
highlighted), `caps-accent`, `heavy-caps`, `condensed`. Sizes are defined for a 1080x1920 frame and
scale to the video. Add a preset by adding an entry to `PRESETS`.

## Sentence selection

You choose the sentences, in the web UI or with `--keep 0,6-7,9`. Nothing is sent anywhere, no API keys needed.

## Limits

- Parakeet (English) is the most accurate for timing. Other languages go through Whisper.
- Cuts assume a voice-over or talking video with a cut per sentence or so. A single continuous shot
  has no scene boundaries to align to, which is fine, it just cuts on the audio.
- Captions are burned in, not a separate track.
- Tested on Linux. The Windows changes (UTF-8 files, ffmpeg path quoting, data directory, tool
  checks) are covered by unit tests but the full pipeline has not been run on a Windows machine.

## Tests

```sh
pip install -e '.[dev]'
pytest
```

## License

MIT, see `LICENSE`. The speech model and the fonts are downloaded separately and keep their own licenses
(Inter, Montserrat, Bebas Neue and Tinos are open fonts).
