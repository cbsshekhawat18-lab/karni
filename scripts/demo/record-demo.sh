#!/usr/bin/env bash
# Record docs/assets/karni-demo.gif, the demo at the top of the README.
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
FILTER="tpad=stop_mode=clone:stop_duration=1.5,fps=8,scale=880:-1:flags=lanczos"
ffmpeg -v error -y -i "$RAW" -vf "${FILTER},palettegen=max_colors=128:stats_mode=diff" "$OUT/palette.png"
ffmpeg -v error -y -i "$RAW" -i "$OUT/palette.png" \
  -lavfi "${FILTER}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
  docs/assets/karni-demo.gif
SIZE=$(stat -f%z docs/assets/karni-demo.gif 2>/dev/null || stat -c%s docs/assets/karni-demo.gif)
echo "docs/assets/karni-demo.gif: $((SIZE / 1024)) KiB"
[ "$SIZE" -le $((5 * 1024 * 1024)) ] || { echo "over 5 MB: lower fps or width" >&2; exit 1; }
