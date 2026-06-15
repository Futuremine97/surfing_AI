#!/usr/bin/env python3
"""Surfing AI — Claude Code MCP server (stdio, stdlib only).

Exposes the local Surfing AI harness to Claude Code (or any MCP client)
over the stdio transport with newline-delimited JSON-RPC 2.0. No external
packages: the protocol is implemented directly, matching the harness's
zero-dependency posture.

Tools:
  surfing_fleet_snapshot     agents/subagents + live thread occupancy (JSON)
  surfing_fleet_control      enable/disable/weight a node, runtime, or role
  surfing_thread_budget      show, or set, the 20..100% thread budget
  surfing_backend_health     safe-vocabulary backend health
  surfing_approvals_list     pending approval queue (latest session)
  surfing_orchestration_plan deterministic parallel plan for a goal

Register in Claude Code via project-scoped .mcp.json (already shipped), or:
  claude mcp add surfing-ai -- python3 integrations/mcp/surfing_ai_mcp.py

Everything runs locally; the harness invariants (allowlist, file guard,
redaction, audit, files_sent_external = 0) are unchanged — these tools
read state and flip local toggles, they do not transmit files.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get(
    "SURFING_AI_ROOT", Path(__file__).resolve().parents[2]))
STATE_ROOT = Path(os.environ.get("SURFING_AI_WORKDIR", ROOT))
sys.path.insert(0, str(ROOT))

SERVER_NAME = "surfing-ai"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL = "2025-06-18"

# ---------------------------------------------------------------- tools

def _tool_fleet_snapshot(args: dict) -> str:
    from harness.agent_fleet import Fleet, snapshot
    fleet = Fleet.load(STATE_ROOT)
    snap = snapshot(fleet, STATE_ROOT, threads=args.get("threads"),
                    tick=int(args.get("tick", 0)))
    return json.dumps(snap, indent=2)


def _tool_fleet_control(args: dict) -> str:
    from harness.agent_fleet import Fleet, snapshot
    action = str(args.get("action", "")).lower()
    target = str(args.get("target", "")).strip()
    if action not in ("enable", "disable", "weight"):
        raise ValueError("action must be enable | disable | weight")
    if not target:
        raise ValueError("target is required (node key, runtime, role, all)")
    fleet = Fleet.load(STATE_ROOT)
    if action == "weight":
        if "weight" not in args:
            raise ValueError("weight is required for action=weight")
        nodes = fleet.set_weight(target, int(args["weight"]))
    else:
        nodes = fleet.set_enabled(target, action == "enable")
    fleet.save(STATE_ROOT)
    summary = {
        "action": action, "target": target,
        "affected": [n.key for n in nodes],
        "snapshot": snapshot(fleet, STATE_ROOT, threads=args.get("threads")),
    }
    return json.dumps(summary, indent=2)


def _tool_thread_budget(args: dict) -> str:
    from harness import thread_budget as tb
    level = args.get("level")
    if level is not None:
        percent = tb.normalize_level(level)
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        (STATE_ROOT / "thread_budget.json").write_text(
            json.dumps({"percent": percent}) + "\n", encoding="utf-8")
        workers = tb.workers_for_percent(percent)
        return (f"thread budget set to {percent}% "
                f"-> {workers} worker(s) of {tb.logical_threads()} "
                f"logical threads\n\n" + tb.format_table())
    return tb.format_table()


def _tool_backend_health(args: dict) -> str:
    from harness.backend_health import format_health, summarize_health
    return format_health(summarize_health(project_root=str(ROOT)))


def _tool_approvals_list(args: dict) -> str:
    from harness.approval_queue import ApprovalQueue
    from harness.audit_log import latest_session_dir
    session = latest_session_dir(ROOT)
    if session is None:
        return "no terminal-private sessions found under reports/"
    records = ApprovalQueue(session / "approvals_queue.jsonl").list()
    if not records:
        return "approval queue is empty"
    return "\n".join(
        f"#{r['id']} [{r['status']}] ({r['kind']}) {r['label']}"
        for r in records)


def _tool_orchestration_plan(args: dict) -> str:
    from harness.multi_agent import build_orchestration_plan
    goal = args.get("goal")
    if not goal:
        raise ValueError("goal is required")
    plan = build_orchestration_plan(
        goal=goal, context=args.get("context", ""),
        providers=args.get("providers"))
    brief = {
        "task_id": plan["task_id"], "goal": plan["goal"],
        "agent_count": plan["agent_count"],
        "subagent_count": plan["subagent_count"],
        "lanes": [
            {"runtime": lane["runtime"],
             "subagents": [s["role"] for s in lane["subagents"]]}
            for lane in plan["lanes"]],
        "fusion": plan["fusion"]["strategy"],
    }
    return json.dumps(brief, indent=2)


TOOLS = [
    {
        "name": "surfing_fleet_snapshot",
        "description": "Agents and subagents with their live thread "
                       "occupancy and utilization, as JSON.",
        "handler": _tool_fleet_snapshot,
        "inputSchema": {
            "type": "object",
            "properties": {
                "threads": {"type": "string",
                            "description": "budget level 20|50|60|70|80|90|"
                                           "100|max (default: saved/all)"},
                "tick": {"type": "integer",
                         "description": "utilization sample tick"},
            },
        },
    },
    {
        "name": "surfing_fleet_control",
        "description": "Enable, disable, or re-weight a fleet node, an "
                       "entire runtime, a role, or all. Persists state.",
        "handler": _tool_fleet_control,
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "enum": ["enable", "disable", "weight"]},
                "target": {"type": "string",
                           "description": "node key (e.g. claude-builder), "
                                          "runtime (claude), role (builder), "
                                          "or all"},
                "weight": {"type": "integer",
                           "description": "required when action=weight"},
            },
            "required": ["action", "target"],
        },
    },
    {
        "name": "surfing_thread_budget",
        "description": "Show the thread budget table, or set the level "
                       "(20/50/60/70/80/90/100/max) used by the fleet and "
                       "max-procs.",
        "handler": _tool_thread_budget,
        "inputSchema": {
            "type": "object",
            "properties": {
                "level": {"type": "string",
                          "description": "20|50|60|70|80|90|100|max"},
            },
        },
    },
    {
        "name": "surfing_backend_health",
        "description": "Backend health using safe vocabulary only.",
        "handler": _tool_backend_health,
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "surfing_approvals_list",
        "description": "List the pending approval queue for the latest "
                       "terminal-private session.",
        "handler": _tool_approvals_list,
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "surfing_orchestration_plan",
        "description": "Build a deterministic parallel explore/build/verify "
                       "plan across runtimes for a goal (no CLIs invoked).",
        "handler": _tool_orchestration_plan,
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "context": {"type": "string"},
                "providers": {"type": "array",
                              "items": {"type": "string"}},
            },
            "required": ["goal"],
        },
    },
]
TOOL_BY_NAME = {t["name"]: t for t in TOOLS}

# ------------------------------------------------------------- protocol

def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def handle(message: dict):
    """Return a response dict, or None for notifications."""
    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": params.get("protocolVersion",
                                          DEFAULT_PROTOCOL),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": [
            {"name": t["name"], "description": t["description"],
             "inputSchema": t["inputSchema"]} for t in TOOLS]})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = TOOL_BY_NAME.get(name)
        if tool is None:
            return _error(req_id, -32602, f"unknown tool: {name}")
        try:
            text = tool["handler"](args)
            return _result(req_id, {
                "content": [{"type": "text", "text": text}],
                "isError": False})
        except Exception as exc:  # surface tool errors to the client
            return _result(req_id, {
                "content": [{"type": "text", "text": f"error: {exc}"}],
                "isError": True})

    if req_id is None:
        return None  # unknown notification
    return _error(req_id, -32601, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
