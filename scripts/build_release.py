#!/usr/bin/env python3
"""Build the downloadable cross-platform release ZIP."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.release_package import write_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="ZIP output path")
    args = parser.parse_args()
    output = write_release(args.output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"archive: {output}")
    print(f"sha256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
