#!/usr/bin/env bash
# Launch the surfing_ai terminal private mode REPL.
# Usage: scripts/surfing_ai_terminal_private.sh [--mode local-only|redacted-external|audit]
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/surfing_ai terminal-private "$@"
