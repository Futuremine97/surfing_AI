#!/usr/bin/env bash
# 카드 HTML → PNG(1080x1080, 2x 고해상도) 추출. Chrome 헤드리스 사용.
# 사용: bash render.sh
set -euo pipefail
cd "$(dirname "$0")"

CHROME=""
for c in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium" \
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  "$(command -v google-chrome || true)" \
  "$(command -v chromium || true)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then CHROME="$c"; break; fi
done

if [ -z "$CHROME" ]; then
  echo "✗ Chrome/Chromium을 찾지 못했습니다. 설치 후 다시 실행하거나, index.html을 열어 직접 캡처하세요." >&2
  exit 1
fi

mkdir -p png
shopt -s nullglob
for f in cards/*.html; do
  name="$(basename "${f%.html}")"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --window-size=1080,1080 \
    --default-background-color=0 \
    --screenshot="png/${name}.png" \
    "file://$(pwd)/${f}" >/dev/null 2>&1
  echo "✓ png/${name}.png"
done
echo "완료 → $(pwd)/png  (2160x2160, 업로드 시 인스타가 자동 축소)"
