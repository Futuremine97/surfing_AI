"""PyInstaller entry point for the Windows .exe (lite desktop).

Bundled layout (see release.yml desktop-lite-windows job):
  harness/      python harness
  desktop/ui/   single-file UI
  scripts/      surfing_ai CLI
The bridge resolves the UI relative to harness/, which PyInstaller
preserves under sys._MEIPASS.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS",
                    Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(BASE))

from harness.desktop_bridge import serve  # noqa: E402


def main() -> None:
    workdir = Path.home() / "SurfingAI"
    serve(root=workdir, open_browser=True)


if __name__ == "__main__":
    main()
