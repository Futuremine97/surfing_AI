"""Generic file access guard for terminal private mode.

Blocks reads of sensitive paths before they can reach any backend or
tool. `.gitignore` is NOT a security boundary — a file being ignored by
git does not mean an AI backend may read it — so this guard never
consults git and works purely from its own deny rules.

Optional local config: `.surfing_ai_private.yaml` (never required,
never committed). A synthetic example lives in
`config/example_private_mode.yaml`.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = ".surfing_ai_private.yaml"

DEFAULT_DENY_PATHS = [
    "private/",
    "secrets/",
    "credentials/",
    "unpublished/",
    "local_only/",
    "reports/private/",
]

DEFAULT_DENY_GLOBS = [
    ".env",
    "*.env",
    "*.pem",
    "*.key",
    "*.secret",
    "*.npy",
    "*.npz",
    "*.pkl",
    "*.sqlite",
    "*.db",
]


@dataclass
class PrivateModeConfig:
    external_backends_default: bool = False
    mcp_default: bool = False
    require_approval_for_file_read: bool = True
    require_approval_for_external_prompt: bool = True
    deny_paths: list[str] = field(default_factory=lambda: list(DEFAULT_DENY_PATHS))
    deny_globs: list[str] = field(default_factory=lambda: list(DEFAULT_DENY_GLOBS))
    source: str = "defaults"


@dataclass
class AccessDecision:
    allowed: bool
    path: str
    reason: str = ""


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "yes", "on", "1")


def load_private_config(root: str | Path = ".") -> PrivateModeConfig:
    """Minimal parser for the documented config shape; pyyaml used if
    available. Unknown keys are ignored. Missing file -> defaults."""
    config = PrivateModeConfig()
    path = Path(root) / CONFIG_NAME
    if not path.is_file():
        return config

    try:
        import yaml  # type: ignore
        data = (yaml.safe_load(path.read_text(encoding="utf-8"))
                or {}).get("private_mode", {})
        if isinstance(data, dict):
            for key in ("external_backends_default", "mcp_default",
                        "require_approval_for_file_read",
                        "require_approval_for_external_prompt"):
                if key in data:
                    setattr(config, key, bool(data[key]))
            if isinstance(data.get("deny_paths"), list):
                config.deny_paths = [str(x) for x in data["deny_paths"]]
            if isinstance(data.get("deny_globs"), list):
                config.deny_globs = [str(x) for x in data["deny_globs"]]
        config.source = str(path)
        return config
    except ImportError:
        pass

    current_list: list[str] | None = None
    for raw in path.read_text(encoding="utf-8",
                              errors="ignore").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_list is not None:
            current_list.append(stripped[2:].strip().strip("'\""))
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        current_list = None
        if key == "deny_paths":
            config.deny_paths = current_list = []
        elif key == "deny_globs":
            config.deny_globs = current_list = []
        elif key in ("external_backends_default", "mcp_default",
                     "require_approval_for_file_read",
                     "require_approval_for_external_prompt") and value:
            setattr(config, key, _parse_bool(value))
    config.source = str(path)
    return config


class FileAccessGuard:
    """Decides whether a path may be read in private mode."""

    def __init__(self, root: str | Path = ".",
                 config: PrivateModeConfig | None = None):
        self.root = Path(root).resolve()
        self.config = config or load_private_config(self.root)

    def check(self, target: str | Path) -> AccessDecision:
        path = Path(target)
        try:
            rel = (path if not path.is_absolute()
                   else path.resolve().relative_to(self.root))
        except ValueError:
            return AccessDecision(False, str(target),
                                  "path is outside the project root")
        posix = rel.as_posix()

        for deny in self.config.deny_paths:
            prefix = deny.strip("/")
            if posix == prefix or posix.startswith(prefix + "/"):
                return AccessDecision(False, posix,
                                      f"matches denied path '{deny}'")

        for pattern in self.config.deny_globs:
            if fnmatch.fnmatch(rel.name, pattern) or fnmatch.fnmatch(
                    posix, pattern):
                return AccessDecision(False, posix,
                                      f"matches denied pattern '{pattern}'")

        return AccessDecision(True, posix)
