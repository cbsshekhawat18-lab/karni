#!/usr/bin/env bash
# Record docs/assets/karni-demo.gif, the demo at the top of the README, and
# docs/assets/karni-demo-poster.png, its first frame.
#
# 1. Follow the README quickstart to a running app (backend and frontend).
#    Other ports: set API_URL and APP_URL.
# 2. Have Playwright (npm install --no-save playwright && npx playwright install
#    chromium; or PW=<path to a playwright package>) and ffmpeg.
# 3. Run this script. The terminal part replays the quickstart's real output,
#    kept in scripts/demo/terminal.html; update it when that output changes.
#
# The GIF must stay under 5 MB so GitHub plays it inline.
set -euo pipefail
cd "$(dirname "$0")/../.."

OUT=$(mktemp -d)
export OUT
node scripts/demo/record.cjs
RAW=$(ls "$OUT"/*.webm)
# The poster first (2.5 s): a paused GIF shows its first frame, and GitHub
# pauses animations for readers who turned autoplay off.
JOIN="[0:v]fps=8,setsar=1[p];[1:v]fps=8,setsar=1[v];[p][v]concat=n=2:v=1:a=0"
FILTER="${JOIN},tpad=stop_mode=clone:stop_duration=1.5,scale=880:-1:flags=lanczos"
POSTER=(-loop 1 -framerate 8 -t 2.5 -i "$OUT/poster.png")
ffmpeg -v error -y "${POSTER[@]}" -i "$RAW" \
  -filter_complex "${FILTER},palettegen=max_colors=128:stats_mode=diff" "$OUT/palette.png"
ffmpeg -v error -y "${POSTER[@]}" -i "$RAW" -i "$OUT/palette.png" \
  -filter_complex "${FILTER}[x];[x][2:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
  docs/assets/karni-demo.gif
cp "$OUT/poster.png" docs/assets/karni-demo-poster.png
SIZE=$(stat -f%z docs/assets/karni-demo.gif 2>/dev/null || stat -c%s docs/assets/karni-demo.gif)
echo "docs/assets/karni-demo.gif: $((SIZE / 1024)) KiB"
[ "$SIZE" -le $((5 * 1024 * 1024)) ] || { echo "over 5 MB: lower fps or width" >&2; exit 1; }
