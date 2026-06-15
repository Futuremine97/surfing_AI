"""End-to-end tests for the Claude Code MCP server (stdio JSON-RPC)."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "integrations" / "mcp" / "surfing_ai_mcp.py"


def _roundtrip(messages, workdir=None):
    """Send JSON-RPC messages (one per line) and collect responses."""
    env = dict(os.environ, SURFING_AI_ROOT=str(ROOT))
    if workdir:
        env["SURFING_AI_WORKDIR"] = str(workdir)
    payload = "".join(json.dumps(m) + "\n" for m in messages)
    proc = subprocess.run(
        [sys.executable, str(SERVER)], input=payload, env=env,
        capture_output=True, text=True, timeout=30)
    out = [json.loads(line) for line in proc.stdout.splitlines()
           if line.strip()]
    return out, proc


def test_initialize_and_tools_list():
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    out, proc = _roundtrip(msgs)
    assert proc.returncode == 0, proc.stderr
    # notification produced no response → exactly two responses
    assert [r["id"] for r in out] == [1, 2]
    init = out[0]["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["serverInfo"]["name"] == "surfing-ai"
    names = {t["name"] for t in out[1]["result"]["tools"]}
    assert {"surfing_fleet_snapshot", "surfing_fleet_control",
            "surfing_thread_budget", "surfing_backend_health",
            "surfing_approvals_list", "surfing_orchestration_plan"} <= names


def test_call_backend_health():
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "surfing_backend_health", "arguments": {}}},
    ]
    out, proc = _roundtrip(msgs)
    res = next(r for r in out if r["id"] == 2)["result"]
    assert res["isError"] is False
    assert res["content"][0]["type"] == "text"
    assert res["content"][0]["text"].strip()


def test_call_fleet_snapshot_is_json():
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "surfing_fleet_snapshot",
                    "arguments": {"threads": "max"}}},
    ]
    out, _ = _roundtrip(msgs)
    res = next(r for r in out if r["id"] == 2)["result"]
    snap = json.loads(res["content"][0]["text"])
    assert len(snap["nodes"]) == 12
    assert snap["allocated_threads"] == snap["budget_threads"]


def test_fleet_control_persists(tmp_path):
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "surfing_fleet_control",
                    "arguments": {"action": "disable", "target": "codex"}}},
    ]
    out, _ = _roundtrip(msgs, workdir=tmp_path)
    res = next(r for r in out if r["id"] == 2)["result"]
    body = json.loads(res["content"][0]["text"])
    assert body["action"] == "disable"
    assert "codex-builder" in body["affected"]
    saved = json.loads((tmp_path / "fleet_state.json").read_text())
    assert "codex-builder" in saved["disabled"]


def test_unknown_tool_is_rpc_error():
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}},
    ]
    out, _ = _roundtrip(msgs)
    err = next(r for r in out if r["id"] == 2)
    assert "error" in err and err["error"]["code"] == -32602


if __name__ == "__main__":
    import traceback
    g = dict(globals())
    fns = [v for k, v in g.items() if k.startswith("test_")]
    p = 0
    for fn in fns:
        try:
            import inspect
            if "tmp_path" in inspect.signature(fn).parameters:
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            p += 1
            print("PASS", fn.__name__)
        except Exception:
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print(f"{p}/{len(fns)} passed")
