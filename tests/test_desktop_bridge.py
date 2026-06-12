"""Desktop bridge tests: in-process HTTP server, real PrivateTerminal
sessions, two-step approval flow, token gating."""

import http.client
import json
import threading
import time

from harness.desktop_bridge import DesktopBridge

TOKEN = "tk12345"  # short synthetic value; real tokens are random hex


class Client:
    def __init__(self, port):
        self.port = port

    def call(self, method, path, body=None, token=TOKEN):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Bridge-Token"] = token
        conn.request(method, path,
                     json.dumps(body) if body is not None else None, headers)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        try:
            return res.status, json.loads(data)
        except json.JSONDecodeError:
            return res.status, data.decode("utf-8", "replace")


def start_bridge(tmp_path, backend_caller=None):
    bridge = DesktopBridge(root=tmp_path, token=TOKEN,
                           backend_caller=backend_caller)
    server = bridge.make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return bridge, server, Client(server.server_address[1])


def stop(bridge, server):
    bridge.shutdown_sessions()
    server.shutdown()
    server.server_close()


def test_token_required(tmp_path):
    bridge, server, client = start_bridge(tmp_path)
    try:
        status, _ = client.call("GET", "/api/sessions", token="")
        assert status == 403
        status, _ = client.call("GET", "/api/sessions", token="wrong")
        assert status == 403
        status, body = client.call("GET", "/api/sessions")
        assert status == 200 and body == []
    finally:
        stop(bridge, server)


def test_session_lifecycle_and_commands(tmp_path):
    bridge, server, client = start_bridge(tmp_path)
    try:
        _, state = client.call("POST", "/api/sessions",
                               {"mode": "local-only"})
        sid = state["id"]
        assert state["mode"] == "local-only"

        _, r = client.call("POST", f"/api/sessions/{sid}/input",
                           {"line": "echo desktop"})
        assert r["status"] == "done" and r["result"] == "desktop"

        _, r = client.call("POST", f"/api/sessions/{sid}/input",
                           {"line": "git push origin main"})
        assert r["result"].startswith("BLOCKED:")

        _, s = client.call("GET", f"/api/sessions/{sid}/state")
        assert s["counters"]["blocked_commands"] == 1
        assert s["counters"]["files_sent_external"] == 0
        kinds = [line["kind"] for line in s["output"]]
        assert "input" in kinds and "result" in kinds

        _, r = client.call("POST", f"/api/sessions/{sid}/close", {})
        assert r["status"] == "closed"
    finally:
        stop(bridge, server)


def test_invalid_mode_and_unknown_session(tmp_path):
    bridge, server, client = start_bridge(tmp_path)
    try:
        _, body = client.call("POST", "/api/sessions", {"mode": "yolo"})
        assert "error" in body
        status, _ = client.call("GET", "/api/sessions/99/state")
        assert status == 404
    finally:
        stop(bridge, server)


def test_two_step_approval_approve(tmp_path):
    sent = []
    bridge, server, client = start_bridge(
        tmp_path,
        backend_caller=lambda b, p: sent.append((b, p)) or "backend says hi")
    try:
        _, state = client.call("POST", "/api/sessions",
                               {"mode": "redacted-external"})
        sid = state["id"]
        _, r = client.call(
            "POST", f"/api/sessions/{sid}/input",
            {"line": ":ask claude key sk-secretsecret123456 review"})
        assert r["status"] == "awaiting_approval"
        assert "EXTERNAL PROMPT PREVIEW" in r["preview"]
        assert "sk-secretsecret123456" not in r["preview"]
        assert sent == []  # nothing sent before the decision

        _, r = client.call("POST", f"/api/sessions/{sid}/decision",
                           {"approve": True})
        assert r["status"] == "done"
        assert len(sent) == 1
        assert "sk-secretsecret123456" not in sent[0][1]

        _, s = client.call("GET", f"/api/sessions/{sid}/state")
        assert s["counters"]["external_backend_calls"] == 1
        assert s["counters"]["files_sent_external"] == 0
    finally:
        stop(bridge, server)


def test_two_step_approval_deny(tmp_path):
    sent = []
    bridge, server, client = start_bridge(
        tmp_path, backend_caller=lambda b, p: sent.append((b, p)))
    try:
        _, state = client.call("POST", "/api/sessions",
                               {"mode": "redacted-external"})
        sid = state["id"]
        _, r = client.call("POST", f"/api/sessions/{sid}/input",
                           {"line": ":ask claude hello"})
        assert r["status"] == "awaiting_approval"
        _, r = client.call("POST", f"/api/sessions/{sid}/decision",
                           {"approve": False})
        assert "not sent" in r["result"]
        assert sent == []
        _, s = client.call("GET", f"/api/sessions/{sid}/state")
        assert s["counters"]["external_backend_calls"] == 0
    finally:
        stop(bridge, server)


def test_orchestrator_info_and_max_sessions(tmp_path):
    from harness.process_orchestrator import max_processes
    bridge, server, client = start_bridge(tmp_path)
    try:
        _, info = client.call("GET", "/api/orchestrator")
        assert info["max_processes"] == max_processes()
        assert info["open_sessions"] == 0
        assert info["available"] == max_processes()

        _, r = client.call("POST", "/api/orchestrator/max_sessions",
                           {"mode": "local-only"})
        assert len(r["created"]) == max_processes()

        # idempotent: already at max, nothing new
        _, r = client.call("POST", "/api/orchestrator/max_sessions",
                           {"mode": "local-only"})
        assert r["created"] == []

        _, info = client.call("GET", "/api/orchestrator")
        assert info["available"] == 0
    finally:
        stop(bridge, server)


def test_ask_refused_fast_in_local_only(tmp_path):
    bridge, server, client = start_bridge(tmp_path)
    try:
        _, state = client.call("POST", "/api/sessions",
                               {"mode": "local-only"})
        sid = state["id"]
        started = time.time()
        _, r = client.call("POST", f"/api/sessions/{sid}/input",
                           {"line": ":ask claude hello"})
        assert r["status"] == "done"
        assert r["result"].startswith("BLOCKED:")
        assert time.time() - started < 5
    finally:
        stop(bridge, server)
