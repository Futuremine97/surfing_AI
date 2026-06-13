#!/usr/bin/env python3
"""Surfing AI — standalone macOS menu-bar app (lite).

A dock-less (LSUIElement) status-bar item that drives the local Surfing
AI bridge. It owns the same python harness the desktop/Tauri app uses, so
the allowlist / file-guard / redaction / audit invariants are unchanged.

Menu:
  Open Surfing AI        open the localhost console in the browser
  Thread Budget ▸        20/50/60/70/80/90/100% (writes thread_budget.json)
  Backend Health         run `surfing_ai backend-health`, show the summary
  Approvals Queue…       run `surfing_ai approvals list`, show it
  Quit

Run from a checkout:
  pip install rumps pyobjc
  python3 desktop/menubar/surfing_menubar.py

Package as a .app:
  python3 scripts/build_menubar_app.py --output dist
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

try:
    import rumps
except ImportError:  # allow import/inspection without the GUI dep present
    rumps = None

# repo root: this file is desktop/menubar/surfing_menubar.py, unless frozen
# inside an .app bundle where SURFING_AI_ROOT is exported by the launcher.
ROOT = Path(os.environ.get(
    "SURFING_AI_ROOT",
    Path(__file__).resolve().parent.parent.parent))
WORKDIR = Path(os.environ.get(
    "SURFING_AI_WORKDIR", Path.home() / "SurfingAI"))
PY = sys.executable or "python3"
SCRIPT = ROOT / "scripts" / "surfing_ai"
ASSETS = Path(__file__).resolve().parent / "assets"

THREAD_LEVELS = (20, 50, 60, 70, 80, 90, 100)
DEFAULT_LEVEL = 50


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run_harness(args: list[str], timeout: int = 20) -> str:
    try:
        out = subprocess.run(
            [PY, str(SCRIPT), *args], cwd=str(ROOT),
            capture_output=True, text=True, timeout=timeout)
        return (out.stdout or out.stderr or "").strip()
    except Exception as exc:  # pragma: no cover - defensive
        return f"error: {exc}"


def _workers_for(percent: int) -> int:
    """Best-effort preview using the harness budget math."""
    try:
        sys.path.insert(0, str(ROOT))
        from harness.thread_budget import workers_for_percent
        return workers_for_percent(percent)
    except Exception:
        return max(1, round((os.cpu_count() or 2) * percent / 100))


def _save_thread_level(percent: int) -> None:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    (WORKDIR / "thread_budget.json").write_text(
        json.dumps({"percent": percent}) + "\n", encoding="utf-8")


if rumps is not None:

    class SurfingMenuBar(rumps.App):
        def __init__(self):
            icon = ASSETS / "menubar_template.png"
            super().__init__(
                "Surfing AI",
                icon=str(icon) if icon.exists() else None,
                template=True, quit_button=None)
            self.port = _free_port()
            self.token = "%016x" % int.from_bytes(os.urandom(8), "big")
            self.url = f"http://127.0.0.1:{self.port}/?token={self.token}"
            self.bridge: subprocess.Popen | None = None
            self.level = self._load_level()
            self._build_menu()
            threading.Thread(target=self._start_bridge, daemon=True).start()

        # ---- menu construction ----
        def _build_menu(self):
            budget = rumps.MenuItem("Thread Budget")
            for p in THREAD_LEVELS:
                item = rumps.MenuItem(
                    f"{p}%  ({_workers_for(p)} workers)",
                    callback=self._make_level_cb(p))
                item.state = 1 if p == self.level else 0
                budget[f"lvl{p}"] = item
            self.menu = [
                rumps.MenuItem("Open Surfing AI", callback=self.open_console),
                None,
                budget,
                rumps.MenuItem("Backend Health", callback=self.backend_health),
                rumps.MenuItem("Approvals Queue…", callback=self.approvals),
                None,
                rumps.MenuItem("Quit Surfing AI", callback=self.quit_app),
            ]
            self._budget_menu = budget

        # ---- lifecycle ----
        def _start_bridge(self):
            try:
                self.bridge = subprocess.Popen(
                    [PY, str(SCRIPT), "desktop",
                     "--port", str(self.port), "--token", self.token,
                     "--root", str(WORKDIR)],
                    cwd=str(ROOT))
            except Exception as exc:  # pragma: no cover
                rumps.notification("Surfing AI", "Bridge failed",
                                   str(exc))

        # ---- callbacks ----
        def open_console(self, _):
            webbrowser.open(self.url)

        def backend_health(self, _):
            summary = _run_harness(["backend-health"]) or "no output"
            rumps.alert("Backend Health", summary)

        def approvals(self, _):
            summary = _run_harness(["approvals", "list"]) or "queue is empty"
            rumps.alert("Approvals Queue", summary)

        def _make_level_cb(self, percent: int):
            def cb(_):
                self.level = percent
                _save_thread_level(percent)
                for p in THREAD_LEVELS:
                    self._budget_menu[f"lvl{p}"].state = (
                        1 if p == percent else 0)
                rumps.notification(
                    "Surfing AI", "Thread budget set",
                    f"{percent}% → {_workers_for(percent)} workers")
            return cb

        def quit_app(self, _):
            if self.bridge and self.bridge.poll() is None:
                self.bridge.terminate()
                time.sleep(0.2)
                if self.bridge.poll() is None:
                    self.bridge.kill()
            rumps.quit_application()

        @staticmethod
        def _load_level() -> int:
            try:
                data = json.loads(
                    (WORKDIR / "thread_budget.json").read_text())
                p = int(data.get("percent", DEFAULT_LEVEL))
                return p if p in THREAD_LEVELS else DEFAULT_LEVEL
            except Exception:
                return DEFAULT_LEVEL


def main() -> int:
    if rumps is None:
        print("rumps is required: pip install rumps pyobjc", file=sys.stderr)
        return 1
    SurfingMenuBar().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
