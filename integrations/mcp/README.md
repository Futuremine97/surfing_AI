# Surfing AI — Claude Code MCP server

A zero-dependency stdio MCP server that exposes the local Surfing AI
harness to Claude Code (or any MCP client). The protocol (newline-delimited
JSON-RPC 2.0 over stdio) is implemented directly in
`surfing_ai_mcp.py` — no `mcp` package required, only `python3`.

## Install

This repository ships a project-scoped `.mcp.json`, so opening the repo in
Claude Code offers the `surfing-ai` server automatically. To register it
explicitly (any scope):

```bash
claude mcp add surfing-ai -- python3 integrations/mcp/surfing_ai_mcp.py
# user scope, from anywhere:
claude mcp add -s user surfing-ai -- python3 /path/to/surfing_AI/integrations/mcp/surfing_ai_mcp.py
```

Verify:

```bash
claude mcp list          # surfing-ai → connected
```

Set `SURFING_AI_ROOT` if the server is launched outside the checkout, and
`SURFING_AI_WORKDIR` to choose where control state (`fleet_state.json`,
`thread_budget.json`) is read/written (defaults to the repo root).

## Tools

| tool | purpose |
|---|---|
| `surfing_fleet_snapshot` | agents/subagents + live thread occupancy (JSON) |
| `surfing_fleet_control` | enable / disable / weight a node, runtime, role, or all |
| `surfing_thread_budget` | show, or set, the 20–100% thread budget |
| `surfing_backend_health` | safe-vocabulary backend health |
| `surfing_approvals_list` | pending approval queue (latest session) |
| `surfing_orchestration_plan` | deterministic explore/build/verify plan for a goal |

Example prompts in Claude Code:

- "Show the surfing-ai fleet snapshot at 80% threads."
- "Disable the codex runtime in the fleet, then weight builder to 5."
- "Set the surfing-ai thread budget to 70%."
- "Build a surfing-ai orchestration plan for: fix the failing tests."

## Safety

The server runs locally and adds no authority. The fleet/thread tools read
state and flip local toggles; health/approvals/plan are read-only. No file
contents are transmitted — the harness `files_sent_external = 0` invariant
is unaffected. (Note: in private mode the harness keeps discovered MCP
servers OFF by default; this server is the opposite direction — it lets
Claude Code drive Surfing AI, not the other way around.)

## Protocol notes

- Transport: stdio, newline-delimited JSON-RPC 2.0 (one message per line).
- Methods: `initialize`, `notifications/initialized`, `ping`, `tools/list`,
  `tools/call`. `initialize` echoes the client's `protocolVersion`.
- Tool results are returned as a single `text` content block; tool errors
  set `isError: true` rather than failing the RPC.
