#!/usr/bin/env bash
# Install the nightly training schedule.
# macOS: launchd job at 02:00, kept awake with caffeinate, stops by 06:30.
# Linux: falls back to a cron entry.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$PROJECT_ROOT/training/logs" "$PROJECT_ROOT/training/checkpoints"

if [[ "$(uname)" == "Darwin" ]]; then
  PLIST_SRC="$PROJECT_ROOT/training/com.surfingai.nightly-train.plist"
  PLIST_DST="$HOME/Library/LaunchAgents/com.surfingai.nightly-train.plist"
  sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$PLIST_SRC" > "$PLIST_DST"
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  launchctl load "$PLIST_DST"
  echo "Installed launchd job: nightly training at 02:00 (stops by 06:30)."
  echo "Logs: $PROJECT_ROOT/training/logs/nightly.log"
  echo "Remove with: launchctl unload '$PLIST_DST' && rm '$PLIST_DST'"
else
  CRON_LINE="0 2 * * * cd $PROJECT_ROOT && python3 training/nightly_train.py --deadline 06:30 >> training/logs/nightly.log 2>&1"
  (crontab -l 2>/dev/null | grep -v nightly_train.py; echo "$CRON_LINE") | crontab -
  echo "Installed cron job: nightly training at 02:00."
fi
