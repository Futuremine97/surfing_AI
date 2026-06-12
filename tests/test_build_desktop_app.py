"""The lite .app builder must produce a valid bundle anywhere (the
.dmg step itself needs macOS hdiutil and is exercised in CI)."""

import os
import plistlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build_desktop_app.py"


def build(tmp_path, *extra):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(tmp_path), *extra],
        capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    return tmp_path / "Surfing AI Desktop.app"


def test_bundle_structure(tmp_path):
    app = build(tmp_path)
    contents = app / "Contents"
    assert (contents / "MacOS" / "SurfingAIDesktop").is_file()
    assert (contents / "Resources" / "scripts" / "surfing_ai").is_file()
    assert (contents / "Resources" / "harness"
            / "desktop_bridge.py").is_file()
    assert (contents / "Resources" / "desktop" / "ui"
            / "index.html").is_file()


def test_launcher_and_cli_are_executable(tmp_path):
    app = build(tmp_path)
    launcher = app / "Contents" / "MacOS" / "SurfingAIDesktop"
    cli = app / "Contents" / "Resources" / "scripts" / "surfing_ai"
    assert os.access(launcher, os.X_OK)
    assert os.access(cli, os.X_OK)
    text = launcher.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash")
    assert "surfing_ai" in text and "--open" in text


def test_info_plist(tmp_path):
    app = build(tmp_path)
    with (app / "Contents" / "Info.plist").open("rb") as fh:
        plist = plistlib.load(fh)
    assert plist["CFBundleExecutable"] == "SurfingAIDesktop"
    assert not plist["CFBundleIdentifier"].endswith(".desktop")
    assert plist["CFBundlePackageType"] == "APPL"


def test_zip_preserves_executable_bits(tmp_path):
    build(tmp_path, "--zip")
    archive = tmp_path / "SurfingAI-Desktop-macos.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as zf:
        info = zf.getinfo(
            "Surfing AI Desktop.app/Contents/MacOS/SurfingAIDesktop")
        assert (info.external_attr >> 16) & 0o111, "exec bit lost"
