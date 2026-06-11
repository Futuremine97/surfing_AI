"""Bridge installed Claude Code plugins to Codex.

What converts where:

  plugin skills/*/SKILL.md   -> ~/.codex/prompts/<plugin>-<skill>.md
  plugin commands/*.md       -> ~/.codex/prompts/<plugin>-<command>.md
  plugin agents/*.md         -> ~/.codex/prompts/<plugin>-agent-<name>.md
  plugin .mcp.json servers   -> ~/.codex/config.toml [mcp_servers.*]

Rules: dry-run first (returns the full plan), config.toml is backed up
before any change, existing prompt files and MCP entries are skipped
(idempotent), and nothing outside ~/.codex is ever written.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
TOML_MCP_SECTION = re.compile(r"^\[mcp_servers\.([^\]]+)\]\s*$")
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class Action:
    kind: str          # "prompt" | "mcp"
    source: str
    target: str
    status: str = "planned"   # planned | written | skipped_exists


@dataclass
class ConversionPlan:
    plugin: str
    plugin_dir: str
    actions: list[Action] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    applied: bool = False

    def to_dict(self) -> dict:
        return {"plugin": self.plugin, "plugin_dir": self.plugin_dir,
                "applied": self.applied, "notes": self.notes,
                "actions": [a.__dict__ for a in self.actions]}


def is_claude_plugin(path: str | Path) -> bool:
    return (Path(path) / PLUGIN_MANIFEST).is_file()


def _plugin_name(plugin_dir: Path) -> str:
    manifest = plugin_dir / PLUGIN_MANIFEST
    try:
        name = json.loads(manifest.read_text(encoding="utf-8")).get("name")
        if name:
            return str(name)
    except (OSError, json.JSONDecodeError):
        pass
    return plugin_dir.name


def _strip_frontmatter(text: str) -> tuple[dict, str]:
    meta: dict = {}
    match = FRONTMATTER.match(text)
    if not match:
        return meta, text
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if _:
            meta[key.strip().lower()] = value.strip()
    return meta, text[match.end():]


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return slug or "item"


def _prompt_body(meta: dict, body: str, source: Path, role_note: str) -> str:
    header = [f"<!-- converted from Claude Code plugin: {source} -->"]
    if meta.get("description"):
        header.append(f"<!-- description: {meta['description']} -->")
    if role_note:
        header.append(role_note)
    return "\n".join(header) + "\n\n" + body.strip() + "\n"


def _existing_mcp_names(config_path: Path) -> set[str]:
    if not config_path.is_file():
        return set()
    names = set()
    for line in config_path.read_text(encoding="utf-8",
                                      errors="ignore").splitlines():
        match = TOML_MCP_SECTION.match(line.strip())
        if match:
            names.add(match.group(1).strip('"'))
    return names


def _toml_value(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(str(value))


def _mcp_section(name: str, server: dict) -> str:
    lines = [f"[mcp_servers.{_safe_slug(name)}]"]
    for key in ("command", "args", "env", "url"):
        value = server.get(key)
        if value is None:
            continue
        if key == "env" and isinstance(value, dict):
            lines.append("env = { " + ", ".join(
                f"{k} = {_toml_value(v)}" for k, v in value.items()) + " }")
        else:
            lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def build_plan(plugin_dir: str | Path,
               home: str | Path | None = None) -> ConversionPlan:
    plugin_dir = Path(plugin_dir).resolve()
    home = Path(home) if home else Path.home()
    if not is_claude_plugin(plugin_dir):
        raise ValueError(f"not a Claude Code plugin (missing "
                         f"{PLUGIN_MANIFEST}): {plugin_dir}")
    name = _plugin_name(plugin_dir)
    prompts_dir = home / ".codex" / "prompts"
    config_path = home / ".codex" / "config.toml"
    plan = ConversionPlan(plugin=name, plugin_dir=str(plugin_dir))

    sources = (
        [(p, "") for p in sorted(plugin_dir.glob("skills/*/SKILL.md"))]
        + [(p, "") for p in sorted(plugin_dir.glob("commands/*.md"))]
        + [(p, "<!-- role: behave as this named subagent -->")
           for p in sorted(plugin_dir.glob("agents/*.md"))]
    )
    for source, role_note in sources:
        if source.parent.name != source.stem and source.name == "SKILL.md":
            stem = source.parent.name
        else:
            stem = source.stem
        prefix = "agent-" if role_note else ""
        target = prompts_dir / f"{_safe_slug(name)}-{prefix}{_safe_slug(stem)}.md"
        action = Action(kind="prompt", source=str(source), target=str(target))
        if target.exists():
            action.status = "skipped_exists"
        plan.actions.append(action)

    mcp_file = plugin_dir / ".mcp.json"
    if mcp_file.is_file():
        existing = _existing_mcp_names(config_path)
        try:
            servers = json.loads(mcp_file.read_text(
                encoding="utf-8")).get("mcpServers", {})
        except json.JSONDecodeError:
            servers = {}
            plan.notes.append(".mcp.json could not be parsed; skipped")
        for server_name in servers:
            action = Action(kind="mcp", source=str(mcp_file),
                            target=f"{config_path} [mcp_servers."
                                   f"{_safe_slug(server_name)}]")
            if _safe_slug(server_name) in existing:
                action.status = "skipped_exists"
            plan.actions.append(action)

    if not plan.actions:
        plan.notes.append("nothing convertible found "
                          "(no skills/commands/agents/.mcp.json)")
    return plan


def apply_plan(plan: ConversionPlan,
               home: str | Path | None = None) -> ConversionPlan:
    home = Path(home) if home else Path.home()
    prompts_dir = home / ".codex" / "prompts"
    config_path = home / ".codex" / "config.toml"
    plugin_dir = Path(plan.plugin_dir)

    mcp_sections: list[str] = []
    servers = {}
    mcp_file = plugin_dir / ".mcp.json"
    if mcp_file.is_file():
        try:
            servers = json.loads(mcp_file.read_text(
                encoding="utf-8")).get("mcpServers", {})
        except json.JSONDecodeError:
            servers = {}

    for action in plan.actions:
        if action.status == "skipped_exists":
            continue
        if action.kind == "prompt":
            source = Path(action.source)
            meta, body = _strip_frontmatter(
                source.read_text(encoding="utf-8", errors="ignore"))
            role_note = ("<!-- role: behave as this named subagent -->"
                         if "/agents/" in action.source else "")
            prompts_dir.mkdir(parents=True, exist_ok=True)
            Path(action.target).write_text(
                _prompt_body(meta, body, source, role_note),
                encoding="utf-8")
            action.status = "written"
        elif action.kind == "mcp":
            match = re.search(r"\[mcp_servers\.([^\]]+)\]", action.target)
            slug = match.group(1) if match else ""
            for server_name, server in servers.items():
                if _safe_slug(server_name) == slug:
                    mcp_sections.append(_mcp_section(server_name, server))
                    action.status = "written"

    if mcp_sections:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.is_file():
            backup = config_path.with_suffix(
                f".toml.bak-{time.strftime('%Y%m%d%H%M%S')}")
            backup.write_bytes(config_path.read_bytes())
            plan.notes.append(f"config.toml backed up to {backup.name}")
        with config_path.open("a", encoding="utf-8") as fh:
            fh.write("\n# Added by Surfing AI plugin bridge "
                     f"(from {plan.plugin})\n")
            fh.write("\n".join(mcp_sections))

    plan.applied = True
    return plan
