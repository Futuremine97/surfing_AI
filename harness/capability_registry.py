"""Capability registry: per-item enable/disable for MCP servers,
skills, and plugins, with a deterministic token-savings estimate.

Token accounting is pure local arithmetic — file sizes divided by four
(the usual chars-per-token heuristic). No model call is ever made to
compute or display these numbers, so showing the savings costs zero
tokens by construction.

Discovery (read-only):
- skills:  skills/<name>/SKILL.md and .agents/skills/<name>/SKILL.md
- plugins: .claude-plugin/plugin.json, integrations/<name>/
- mcp:     servers listed in .mcp.json (standard config), if present

State lives in `.surfing_ai_capabilities.json` at the project root
(gitignored). Defaults follow the private-mode posture: MCP servers
start disabled; skills and plugins start enabled.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

STATE_FILE = ".surfing_ai_capabilities.json"
MCP_DEFAULT_TOKENS = 600          # typical tool-schema overhead per server
PLUGIN_TOKEN_CAP = 4000
DEFAULT_ENABLED = {"mcp": False, "skill": True, "plugin": True}
TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".toml", ".txt"}


@dataclass
class Capability:
    id: str
    kind: str          # mcp | skill | plugin
    name: str
    enabled: bool
    est_tokens: int    # context overhead if enabled, per request
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


def _estimate_tokens_file(path: Path) -> int:
    try:
        return max(1, path.stat().st_size // 4)
    except OSError:
        return 1


def _estimate_tokens_dir(path: Path, cap: int = PLUGIN_TOKEN_CAP) -> int:
    total = 0
    for child in sorted(path.rglob("*")):
        if child.is_file() and child.suffix in TEXT_SUFFIXES:
            total += child.stat().st_size // 4
        if total >= cap:
            return cap
    return max(1, total)


class CapabilityRegistry:
    def __init__(self, root: str | Path = "."):
        self.root = Path(root)
        self.state_path = self.root / STATE_FILE

    # ---- state -------------------------------------------------------------

    def _overrides(self) -> dict[str, bool]:
        if not self.state_path.is_file():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            overrides = data.get("overrides", {})
            return {str(k): bool(v) for k, v in overrides.items()}
        except (json.JSONDecodeError, OSError):
            return {}

    def set_enabled(self, capability_id: str, enabled: bool) -> dict:
        known = {c.id for c in self.discover()}
        if capability_id not in known:
            return {"error": f"unknown capability '{capability_id}'"}
        overrides = self._overrides()
        overrides[capability_id] = bool(enabled)
        self.state_path.write_text(
            json.dumps({"overrides": overrides}, indent=2, sort_keys=True),
            encoding="utf-8")
        return {"id": capability_id, "enabled": bool(enabled)}

    # ---- discovery -----------------------------------------------------------

    def discover(self) -> list[Capability]:
        overrides = self._overrides()
        capabilities: list[Capability] = []

        def add(kind: str, cap_id: str, name: str, est: int, source: str):
            enabled = overrides.get(cap_id, DEFAULT_ENABLED[kind])
            capabilities.append(Capability(cap_id, kind, name, enabled,
                                           est, source))

        # skills
        for skills_dir in (self.root / "skills",
                           self.root / ".agents" / "skills"):
            if not skills_dir.is_dir():
                continue
            for entry in sorted(skills_dir.iterdir()):
                skill_md = entry / "SKILL.md"
                if entry.is_dir() and skill_md.is_file():
                    rel = entry.relative_to(self.root).as_posix()
                    add("skill", f"skill:{rel}", entry.name,
                        _estimate_tokens_file(skill_md), rel)

        # plugins
        plugin_json = self.root / ".claude-plugin" / "plugin.json"
        if plugin_json.is_file():
            try:
                name = json.loads(
                    plugin_json.read_text(encoding="utf-8")).get(
                        "name", ".claude-plugin")
            except (json.JSONDecodeError, OSError):
                name = ".claude-plugin"
            add("plugin", "plugin:.claude-plugin", str(name),
                _estimate_tokens_dir(plugin_json.parent), ".claude-plugin")
        integrations = self.root / "integrations"
        if integrations.is_dir():
            for entry in sorted(integrations.iterdir()):
                if entry.is_dir():
                    rel = entry.relative_to(self.root).as_posix()
                    add("plugin", f"plugin:{rel}", entry.name,
                        _estimate_tokens_dir(entry), rel)

        # mcp servers (.mcp.json — standard "mcpServers" map)
        mcp_json = self.root / ".mcp.json"
        if mcp_json.is_file():
            try:
                servers = json.loads(
                    mcp_json.read_text(encoding="utf-8")).get(
                        "mcpServers", {})
            except (json.JSONDecodeError, OSError):
                servers = {}
            for name in sorted(servers):
                add("mcp", f"mcp:{name}", str(name), MCP_DEFAULT_TOKENS,
                    ".mcp.json")

        return capabilities

    # ---- savings -------------------------------------------------------------

    def summary(self) -> dict:
        """Deterministic token accounting; never calls any model."""
        capabilities = self.discover()
        baseline = sum(c.est_tokens for c in capabilities)
        enabled = sum(c.est_tokens for c in capabilities if c.enabled)
        saved = baseline - enabled
        return {
            "capabilities": len(capabilities),
            "enabled_count": sum(1 for c in capabilities if c.enabled),
            "baseline_tokens_per_request": baseline,
            "enabled_tokens_per_request": enabled,
            "saved_tokens_per_request": saved,
            "saved_percent": round(100 * saved / baseline, 1)
                             if baseline else 0.0,
            "saved_tokens_per_100_requests": saved * 100,
            "computation": "local file-size arithmetic; zero model tokens",
        }

    def listing(self) -> dict:
        return {"capabilities": [c.to_dict() for c in self.discover()],
                "summary": self.summary()}
