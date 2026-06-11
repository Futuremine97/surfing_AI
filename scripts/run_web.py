#!/usr/bin/env python3
"""Launch the local website and product console."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.web_app import main


if __name__ == "__main__":
    raise SystemExit(main())
