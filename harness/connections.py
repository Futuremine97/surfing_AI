"""Discover connected runtimes, MCP servers, and skills on this machine.

Read-only scans of the well-known config locations for each runtime:

  claude  ~/.claude.json (mcpServers), ~/.claude/skills/, project .mcp.json,
          project .claude/skills/ and skills/
  codex   ~/.codex/config.toml ([mcp_servers.*]), ~/.codex/prompts/,
          project .codex/
  gemini / antigravity
          ~/.gemini/settings.json (mcpServers), ~/.antigravity/settings.json,
          project .agents/skills/

Every returned item carries the absolute path it came from, so a UI can
offer "reveal in file manager". `paths()` exposes the whitelist used to
validate open requests.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

RUNTIME_BINARIES = {
    "claude": ["claude"],
    "codex": ["codex"],
    "antigravity": ["antigravity", "gemini"],
}

TOML_MCP_SECTION = re.compile(r"^\[mcp_servers\.([^\]]+)\]\s*$")
FRONTMATTER_FIELD = re.compile(r"^(name|description):\s*(.+)$", re.IGNORECASE)


@dataclass
class Connection:
    runtime: str
    kind: str          # "runtime" | "mcp" | "skill"
    name: str
    detail: str = ""
    path: str = ""
    found: bool = True


@dataclass
class ConnectionReport:
    runtimes: list[Connection] = field(default_factory=list)
    mcp_servers: list[Connection] = field(default_factory=list)
    skills: list[Connection] = field(default_factory=list)
    plugins: list[Connection] = field(default_factory=list)

    def paths(self) -> set[str]:
        return {c.path for c in (self.runtimes + self.mcp_servers
                                 + self.skills + self.plugins) if c.path}

    def to_dict(self) -> dict:
        return {"runtimes": [asdict(c) for c in self.runtimes],
                "mcp_servers": [asdict(c) for c in self.mcp_servers],
                "skills": [asdict(c) for c in self.skills],
                "plugins": [asdict(c) for c in self.plugins]}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _mcp_detail(config) -> str:
    if isinstance(config, dict):
        if config.get("command"):
            return str(config["command"])
        if config.get("url"):
            return str(config["url"])
    return "configured"


def _scan_runtime_clis() -> list[Connection]:
    items = []
    for runtime, binaries in RUNTIME_BINARIES.items():
        located = None
        binary = binaries[0]
        for candidate in binaries:
            located = shutil.which(candidate)
            if located:
                binary = candidate
                break
        items.append(Connection(
            runtime=runtime, kind="runtime", name=binary,
            detail="CLI found" if located else "CLI not found",
            path=located or "", found=bool(located)))
    return items


def _scan_claude_mcp(home: Path, project_root: Path) -> list[Connection]:
    items = []
    config = _read_json(home / ".claude.json")
    for name, server in (config.get("mcpServers") or {}).items():
        items.append(Connection("claude", "mcp", name, _mcp_detail(server),
                                str(home / ".claude.json")))
    for project, settings in (config.get("projects") or {}).items():
        for name, server in (settings.get("mcpServers") or {}).items():
            items.append(Connection("claude", "mcp", f"{name} ({project})",
                                    _mcp_detail(server),
                                    str(home / ".claude.json")))
    project_mcp = project_root / ".mcp.json"
    if project_mcp.is_file():
        for name, server in (_read_json(project_mcp).get("mcpServers")
                             or {}).items():
            items.append(Connection("claude", "mcp", name,
                                    _mcp_detail(server), str(project_mcp)))
    return items


def _scan_codex_mcp(home: Path) -> list[Connection]:
    config = home / ".codex" / "config.toml"
    if not config.is_file():
        return []
    items = []
    for line in config.read_text(encoding="utf-8",
                                 errors="ignore").splitlines():
        match = TOML_MCP_SECTION.match(line.strip())
        if match:
            items.append(Connection("codex", "mcp",
                                    match.group(1).strip('"'),
                                    "configured", str(config)))
    return items


def _scan_gemini_mcp(home: Path) -> list[Connection]:
    items = []
    for runtime, settings_path in (
        ("antigravity", home / ".gemini" / "settings.json"),
        ("antigravity", home / ".antigravity" / "settings.json"),
    ):
        if settings_path.is_file():
            for name, server in (_read_json(settings_path).get("mcpServers")
                                 or {}).items():
                items.append(Connection(runtime, "mcp", name,
                                        _mcp_detail(server),
                                        str(settings_path)))
    return items


def _skill_meta(skill_md: Path) -> tuple[str, str]:
    name, description = skill_md.parent.name, ""
    try:
        for line in skill_md.read_text(encoding="utf-8",
                                       errors="ignore").splitlines()[:15]:
            match = FRONTMATTER_FIELD.match(line.strip())
            if match:
                if match.group(1).lower() == "name":
                    name = match.group(2).strip()
                else:
                    description = match.group(2).strip()[:140]
    except OSError:
        pass
    return name, description


def _scan_skills(home: Path, project_root: Path) -> list[Connection]:
    roots = [
        ("claude", home / ".claude" / "skills"),
        ("claude", project_root / ".claude" / "skills"),
        ("claude", project_root / "skills"),
        ("antigravity", project_root / ".agents" / "skills"),
        ("antigravity", project_root / "integrations" / "antigravity" / "skills"),
    ]
    items = []
    seen: set[str] = set()
    for runtime, base in roots:
        if not base.is_dir():
            continue
        for skill_md in sorted(base.glob("*/SKILL.md")):
            key = str(skill_md.resolve())
            if key in seen:
                continue
            seen.add(key)
            name, description = _skill_meta(skill_md)
            items.append(Connection(runtime, "skill", name, description,
                                    str(skill_md.parent)))
    prompts = home / ".codex" / "prompts"
    if prompts.is_dir():
        for prompt in sorted(prompts.glob("*.md")):
            items.append(Connection("codex", "skill", prompt.stem,
                                    "custom prompt", str(prompt)))
    return items


def _plugin_path_guess(home: Path, marketplace: str, plugin: str) -> str:
    candidates = [
        home / ".claude" / "plugins" / "cache" / marketplace / plugin,
        home / ".claude" / "plugins" / "cache" / marketplace,
        home / ".claude" / "plugins" / "marketplaces" / marketplace,
        home / ".claude" / "plugins",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def _scan_claude_plugins(home: Path) -> list[Connection]:
    """Installed Claude Code plugins: enabledPlugins in settings.json plus
    marketplaces registered in plugins/config.json."""
    items = []
    settings = _read_json(home / ".claude" / "settings.json")
    for key, enabled in (settings.get("enabledPlugins") or {}).items():
        name, _, marketplace = key.partition("@")
        items.append(Connection(
            runtime="claude", kind="plugin", name=name,
            detail=(f"marketplace: {marketplace or 'unknown'} · "
                    f"{'enabled' if enabled else 'disabled'}"),
            path=_plugin_path_guess(home, marketplace, name),
            found=bool(enabled)))

    config = _read_json(home / ".claude" / "plugins" / "config.json")
    marketplaces = (config.get("marketplaces")
                    or config.get("repositories") or {})
    for marketplace in marketplaces:
        items.append(Connection(
            runtime="claude", kind="plugin", name=marketplace,
            detail="marketplace",
            path=_plugin_path_guess(home, marketplace, "")))

    cache = home / ".claude" / "plugins" / "cache"
    if cache.is_dir():
        seen = {item.name for item in items}
        for entry in sorted(cache.iterdir()):
            if entry.is_dir() and entry.name not in seen:
                items.append(Connection(
                    runtime="claude", kind="plugin", name=entry.name,
                    detail="cached marketplace", path=str(entry)))
    return items


def scan_connections(home: str | Path | None = None,
                     project_root: str | Path = ".") -> ConnectionReport:
    home = Path(home) if home else Path.home()
    project_root = Path(project_root).resolve()
    return ConnectionReport(
        runtimes=_scan_runtime_clis(),
        mcp_servers=(_scan_claude_mcp(home, project_root)
                     + _scan_codex_mcp(home)
                     + _scan_gemini_mcp(home)),
        skills=_scan_skills(home, project_root),
        plugins=_scan_claude_plugins(home),
    )
