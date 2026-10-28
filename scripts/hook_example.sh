#!/usr/bin/env bash
# Example: render two hook versions (A/B test) on the full video, black rounded box, yellow text,
# white captions. "//" in the hook text is an explicit line break.
# Usage: scripts/hook_example.sh /path/to/video.mp4 [output_dir]
# Optional: ONLY="A" scripts/hook_example.sh video.mp4    to build just one of them.
set -euo pipefail

VIDEO="${1:?usage: hook_example.sh /path/to/video.mp4 [output_dir]}"
OUT="${2:-out}"
ONLY="${ONLY:-A B}"
mkdir -p "$OUT"

TEXT_A="WHERE I FINALLY FOUND MY // FAVORITE COFFEE SHOP"
TEXT_B="I ALMOST GAVE UP ON MY // MORNING COFFEE"

OPTS=(--keep all --style plain --brand "Acme Coffee"
      --hook-font montserrat-extrabold --hook-color FFD400 --hook-size 140 --hook-top 170
      --hook-line-height 0.8 --hook-fade-in 0 --hook-shadow 0 --hook-max-lines 2 --hook-seconds 4.3
      --hook-outline 0 --hook-backdrop rounded --hook-backdrop-color 000000 --hook-backdrop-alpha 0
      --hook-pad-x 40 --hook-pad-y 24 --hook-radius 26
      --preset superfast --crf 21)

# transcript and scene cuts are computed once and reused by both renders
opencaptions analyze "$VIDEO" > /dev/null

for v in $ONLY; do
  case "$v" in
    A) opencaptions render "$VIDEO" "${OPTS[@]}" --hook "$TEXT_A" -o "$OUT/hook_A_box.mp4" ;;
    B) opencaptions render "$VIDEO" "${OPTS[@]}" --hook "$TEXT_B" -o "$OUT/hook_B_box.mp4" ;;
    *) echo "unknown version $v (use A or B)" >&2; exit 1 ;;
  esac
done

