#!/usr/bin/env python3
"""Build "Surfing AI Menu Bar (lite)" — a dock-less macOS menu-bar app.

Self-contained .app whose executable launches the rumps status-bar app,
which in turn owns the Python bridge. LSUIElement = true means no Dock
icon and no app-switcher entry: it lives only in the top-right menu bar.

  python3 scripts/build_menubar_app.py --output dist
  python3 scripts/build_menubar_app.py --output dist --dmg
  python3 scripts/build_menubar_app.py --output dist --zip

Runtime requirement on the target Mac: python3 with `rumps` available
(pip install rumps pyobjc). The bundle binds 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "Surfing AI Menu Bar"
BUNDLE_ID = "ai.surfing.workspace.menubar"
VERSION = "0.1.0"

LAUNCHER = """#!/bin/bash
# Surfing AI Menu Bar (lite) launcher — starts the dock-less status-bar
# app. Localhost only.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
RES="$HERE/../Resources"
PY="$(command -v python3 || echo /usr/bin/python3)"
export SURFING_AI_ROOT="$RES"
export SURFING_AI_WORKDIR="$HOME/SurfingAI"
mkdir -p "$SURFING_AI_WORKDIR"
exec "$PY" "$RES/desktop/menubar/surfing_menubar.py"
"""

RESOURCE_SETS = [
    ("harness", "*.py", "harness"),
    ("scripts", "surfing_ai", "scripts"),
    ("desktop/menubar", "surfing_menubar.py", "desktop/menubar"),
    ("desktop/menubar/assets", "*.png", "desktop/menubar/assets"),
    ("config", "example_private_mode.yaml", "config"),
]


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
               | stat.S_IXOTH)


def build_app(output: Path) -> Path:
    app = output / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    macos_dir = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos_dir.mkdir(parents=True)
    resources.mkdir(parents=True)

    for src_dir, pattern, dest in RESOURCE_SETS:
        dest_dir = resources / dest
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted((ROOT / src_dir).glob(pattern)):
            if src.is_file():
                shutil.copy2(src, dest_dir / src.name)
    _make_executable(resources / "scripts" / "surfing_ai")

    icns = ROOT / "desktop" / "src-tauri" / "icons" / "icon.icns"
    if icns.is_file():
        shutil.copy2(icns, resources / "icon.icns")

    launcher = macos_dir / "SurfingAIMenuBar"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    _make_executable(launcher)

    plist = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "SurfingAIMenuBar",
        "CFBundleIconFile": "icon.icns",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        # menu-bar-only agent: no Dock icon, no app switcher entry
        "LSUIElement": True,
    }
    with (app / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(plist, fh)
    print(f"app bundle: {app}")
    return app


def build_dmg(app: Path, output: Path) -> Path:
    dmg = output / "SurfingAI-MenuBar.dmg"
    if dmg.exists():
        dmg.unlink()
    staging = output / "menubar-dmg-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    shutil.copytree(app, staging / app.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")
    subprocess.run(
        ["hdiutil", "create", "-volname", APP_NAME, "-srcfolder",
         str(staging), "-ov", "-format", "UDZO", str(dmg)], check=True)
    shutil.rmtree(staging)
    print(f"dmg: {dmg}")
    return dmg


def build_zip(app: Path, output: Path) -> Path:
    archive = output / "SurfingAI-MenuBar-macos.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(app.rglob("*")):
            rel = path.relative_to(app.parent)
            if path.is_symlink() or not path.is_file():
                continue
            info = zipfile.ZipInfo(str(rel))
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            zf.writestr(info, path.read_bytes(), zipfile.ZIP_DEFLATED)
    print(f"zip: {archive}")
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist")
    parser.add_argument("--dmg", action="store_true",
                        help="also build a .dmg (requires macOS hdiutil)")
    parser.add_argument("--zip", action="store_true",
                        help="also build an executable-bit-preserving zip")
    args = parser.parse_args(argv)

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    app = build_app(output)
    if args.dmg:
        if shutil.which("hdiutil") is None:
            print("error: hdiutil not found — run --dmg on macOS",
                  file=sys.stderr)
            return 1
        build_dmg(app, output)
    if args.zip:
        build_zip(app, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
