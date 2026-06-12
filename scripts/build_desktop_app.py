#!/usr/bin/env python3
"""Build "Surfing AI Desktop (lite)" with zero toolchain.

Creates a fully self-contained macOS .app bundle whose executable is a
shell launcher that starts the Python bridge and opens the UI in the
default browser. No Rust, no Node, no compilation — the only runtime
requirement is python3, which macOS offers out of the box.

  python3 scripts/build_desktop_app.py --output dist          # .app
  python3 scripts/build_desktop_app.py --output dist --dmg    # + .dmg (hdiutil, macOS)
  python3 scripts/build_desktop_app.py --output dist --zip    # + .zip (any OS)

The .dmg step shells out to hdiutil and therefore must run on macOS
(your Mac or a macOS CI runner). The .app/.zip build runs anywhere.
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
APP_NAME = "Surfing AI Desktop"
BUNDLE_ID = "ai.surfing.workspace.lite"
VERSION = "0.1.0"

LAUNCHER = """#!/bin/bash
# Surfing AI Desktop (lite) launcher — starts the local bridge and
# opens the UI in the default browser. Localhost only.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
RES="$HERE/../Resources"
PY="$(command -v python3 || echo /usr/bin/python3)"
WORKDIR="$HOME/SurfingAI"
mkdir -p "$WORKDIR"
exec "$PY" "$RES/scripts/surfing_ai" desktop --root "$WORKDIR" --open
"""

RESOURCE_SETS = [
    ("harness", "*.py", "harness"),
    ("scripts", "surfing_ai", "scripts"),
    ("desktop/ui", "index.html", "desktop/ui"),
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

    # python payload
    for src_dir, pattern, dest in RESOURCE_SETS:
        dest_dir = resources / dest
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted((ROOT / src_dir).glob(pattern)):
            if src.is_file():
                shutil.copy2(src, dest_dir / src.name)
    _make_executable(resources / "scripts" / "surfing_ai")

    # icon
    icns = ROOT / "desktop" / "src-tauri" / "icons" / "icon.icns"
    if icns.is_file():
        shutil.copy2(icns, resources / "icon.icns")

    # launcher
    launcher = macos_dir / "SurfingAIDesktop"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    _make_executable(launcher)

    # Info.plist
    plist = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "SurfingAIDesktop",
        "CFBundleIconFile": "icon.icns",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }
    with (app / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(plist, fh)
    print(f"app bundle: {app}")
    return app


def build_dmg(app: Path, output: Path) -> Path:
    dmg = output / "SurfingAI-Desktop.dmg"
    if dmg.exists():
        dmg.unlink()
    staging = output / "dmg-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    shutil.copytree(app, staging / app.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")
    subprocess.run(
        ["hdiutil", "create", "-volname", APP_NAME, "-srcfolder",
         str(staging), "-ov", "-format", "UDZO", str(dmg)],
        check=True)
    shutil.rmtree(staging)
    print(f"dmg: {dmg}")
    return dmg


def build_zip(app: Path, output: Path) -> Path:
    """Zip that preserves the executable bits (any OS)."""
    archive = output / "SurfingAI-Desktop-macos.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(app.rglob("*")):
            rel = path.relative_to(app.parent)
            if path.is_symlink() or not path.is_file():
                continue
            info = zipfile.ZipInfo(str(rel))
            info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
            zf.writestr(info, path.read_bytes(),
                        zipfile.ZIP_DEFLATED)
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
