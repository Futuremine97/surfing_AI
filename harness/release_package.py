"""Build a curated, runnable release ZIP without private local artifacts."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT_NAME = "surfing-ai"
ARCHIVE_NAME = f"{PRODUCT_NAME}.zip"

TOP_LEVEL_FILES = (
    "AGENTS.md",
    "LICENSE",
    "README.md",
    "pyproject.toml",
)

PACKAGE_DIRECTORIES = (
    ".agents",
    ".claude-plugin",
    ".codex",
    "agents",
    "config",
    "harness",
    "integrations",
    "skills/route-and-verify",
    "web",
)

PACKAGE_SCRIPTS = (
    "scripts/run_tests.py",
    "scripts/run_web.py",
)

LAUNCHER_FILES = {
    "packaging/INSTALL.txt": "INSTALL.txt",
    "packaging/launch.command": "launch.command",
    "packaging/launch.sh": "launch.sh",
    "packaging/launch.bat": "launch.bat",
}

EXCLUDED_NAMES = {
    ".DS_Store",
    "__pycache__",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def read_version(root: str | Path = ROOT) -> str:
    text = (Path(root) / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("project version not found in pyproject.toml")
    return match.group(1)


def archive_filename(root: str | Path = ROOT) -> str:
    return f"{PRODUCT_NAME}-{read_version(root)}.zip"


def _is_package_file(path: Path) -> bool:
    return (
        path.is_file()
        and not any(part in EXCLUDED_NAMES for part in path.parts)
        and path.suffix not in EXCLUDED_SUFFIXES
    )


def _iter_package_files(root: Path):
    for relative in TOP_LEVEL_FILES:
        path = root / relative
        if path.is_file():
            yield path, Path(relative)

    for relative in PACKAGE_SCRIPTS:
        path = root / relative
        if path.is_file():
            yield path, Path(relative)

    for relative in PACKAGE_DIRECTORIES:
        directory = root / relative
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if _is_package_file(path):
                yield path, path.relative_to(root)

    for source, destination in LAUNCHER_FILES.items():
        path = root / source
        if path.is_file():
            yield path, Path(destination)


def build_release_bytes(root: str | Path = ROOT) -> bytes:
    root = Path(root).resolve()
    prefix = f"{PRODUCT_NAME}-{read_version(root)}"
    output = io.BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for source, relative in _iter_package_files(root):
            destination = Path(prefix) / relative
            info = zipfile.ZipInfo.from_file(source, str(destination))
            if relative.name in ("launch.command", "launch.sh"):
                info.external_attr = (0o100755 & 0xFFFF) << 16
            with source.open("rb") as handle:
                archive.writestr(
                    info,
                    handle.read(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
    return output.getvalue()


def write_release(
    output: str | Path | None = None,
    root: str | Path = ROOT,
) -> Path:
    root = Path(root).resolve()
    output_path = Path(output) if output else root / "dist" / archive_filename(root)
    if not output_path.is_absolute():
        output_path = root / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_release_bytes(root))
    return output_path
