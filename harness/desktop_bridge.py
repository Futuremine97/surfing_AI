"""Desktop bridge: localhost JSON API + UI server for the Surfing AI
desktop app (Tauri shell or plain browser).

Multi-session: each session wraps one PrivateTerminal (terminal private
mode) and keeps an output buffer. External-prompt approvals become a
two-step HTTP flow — `input` returns ``awaiting_approval`` with the
preview, and a separate explicit `decision` call answers y/N (no
decision within the timeout = deny, same default-N invariant as the
REPL).

Security model:
- binds 127.0.0.1 only; an optional shared token gates every request
- all real enforcement (allowlist, file guard, redaction, counters,
  audit) lives in PrivateTerminal — the bridge adds no new authority
- the bridge never reads files itself and never talks to the network
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from harness.backend_health import format_health, summarize_health
from harness.terminal_private_mode import (DEFAULT_MODE, MODES, QUIT,
                                           PrivateTerminal)

UI_PATH = Path(__file__).resolve().parent.parent / "desktop" / "ui" / "index.html"
APPROVAL_TIMEOUT = 300  # seconds; expiry = deny (default N)
OUTPUT_LIMIT = 2000     # lines kept per session


class BridgeSession:
    """One PrivateTerminal plus output buffer and approval state."""

    def __init__(self, session_id: int, root: str | Path,
                 mode: str = DEFAULT_MODE, backend_caller=None):
        self.id = session_id
        self.lock = threading.Lock()
        self.output: list[dict] = []
        self.pending: dict | None = None      # {"preview": str}
        self._decision: str | None = None
        self._decision_event = threading.Event()
        self._ask_thread: threading.Thread | None = None
        self._ask_result: str | None = None
        self.terminal = PrivateTerminal(
            root=root, mode=mode,
            input_fn=self._approval_input,
            output_fn=self._capture_output,
            backend_caller=backend_caller)
        self.created = time.time()
        self.closed = False

    # ---- terminal callbacks ----------------------------------------------

    def _capture_output(self, *args, **_kwargs) -> None:
        text = " ".join(str(a) for a in args)
        self._emit("info", text)
        # the preview is printed by ask_external right before input_fn
        if text.startswith("EXTERNAL PROMPT PREVIEW"):
            self.pending = {"preview": text}

    def _approval_input(self, prompt: str = "") -> str:
        """Blocks the ask thread until /decision or timeout (=deny)."""
        self._decision_event.wait(timeout=APPROVAL_TIMEOUT)
        decision = self._decision or "n"
        self._decision = None
        self._decision_event.clear()
        self.pending = None
        return decision

    def _emit(self, kind: str, text: str) -> None:
        self.output.append({"ts": time.time(), "kind": kind, "text": text})
        del self.output[:-OUTPUT_LIMIT]

    # ---- API operations ----------------------------------------------------

    def feed(self, line: str) -> dict:
        """Handle one input line. :ask runs on a worker thread so the
        HTTP request can return awaiting_approval immediately."""
        with self.lock:
            if self.closed:
                return {"error": "session closed"}
            if self._ask_thread and self._ask_thread.is_alive():
                return {"status": "busy",
                        "detail": "an approval is already pending"}
            self._emit("input", line)

            if line.strip().startswith(":ask"):
                self._ask_result = None

                def runner() -> None:
                    result = self.terminal.handle(line)
                    self._ask_result = str(result)
                    self._emit("result", str(result))

                self._ask_thread = threading.Thread(target=runner,
                                                    daemon=True)
                self._ask_thread.start()
                # wait briefly for either the preview or a fast refusal
                for _ in range(100):
                    if self.pending or not self._ask_thread.is_alive():
                        break
                    time.sleep(0.02)
                if self.pending:
                    return {"status": "awaiting_approval",
                            "preview": self.pending["preview"]}
                self._ask_thread.join(timeout=5)
                return {"status": "done", "result": self._ask_result or ""}

            result = self.terminal.handle(line)
            if result is QUIT:
                return self.close()
            text = str(result)
            if text:
                self._emit("result", text)
            return {"status": "done", "result": text}

    def decide(self, approve: bool) -> dict:
        with self.lock:
            if not (self._ask_thread and self._ask_thread.is_alive()):
                return {"error": "no approval pending"}
            self._decision = "y" if approve else "n"
            self._decision_event.set()
            self._ask_thread.join(timeout=30)
            return {"status": "done", "result": self._ask_result or ""}

    def state(self, tail: int = 200) -> dict:
        counters = self.terminal.audit.counters
        return {
            "id": self.id,
            "mode": self.terminal.mode,
            "closed": self.closed,
            "pending": self.pending,
            "audit_dir": str(self.terminal.audit.dir),
            "counters": {
                "external_backend_calls": counters.external_backend_calls,
                "mcp_calls": counters.mcp_calls,
                "blocked_commands": counters.blocked_commands,
                "files_sent_external": counters.files_sent_external,
            },
            "approvals_pending": [
                {"id": r["id"], "label": r["label"]}
                for r in self.terminal.queue.pending()],
            "output": self.output[-tail:],
        }

    def close(self) -> dict:
        if not self.closed:
            self.closed = True
            summary = self.terminal.close()
            self._emit("info", f"summary written: {summary}")
        return {"status": "closed", "id": self.id}


class DesktopBridge:
    def __init__(self, root: str | Path = ".", token: str | None = None,
                 backend_caller=None):
        self.root = Path(root)
        self.token = token if token is not None else secrets.token_hex(16)
        self.backend_caller = backend_caller
        self.sessions: dict[int, BridgeSession] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    # ---- session management -----------------------------------------------

    def create_session(self, mode: str = DEFAULT_MODE) -> dict:
        if mode not in MODES:
            return {"error": f"unknown mode '{mode}'"}
        with self._lock:
            session_id = self._next_id
            self._next_id += 1
            session = BridgeSession(session_id, self.root, mode,
                                    self.backend_caller)
            self.sessions[session_id] = session
        return session.state()

    def list_sessions(self) -> list[dict]:
        return [{"id": s.id, "mode": s.terminal.mode, "closed": s.closed,
                 "pending": bool(s.pending)}
                for s in self.sessions.values()]

    # ---- HTTP plumbing ------------------------------------------------------

    def make_server(self, host: str = "127.0.0.1",
                    port: int = 0) -> ThreadingHTTPServer:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            # -- helpers --
            def _send(self, code: int, body, content_type="application/json"):
                data = (body if isinstance(body, bytes)
                        else json.dumps(body, ensure_ascii=False,
                                        default=str).encode("utf-8"))
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authorized(self, query: dict) -> bool:
                if not bridge.token:
                    return True
                supplied = (self.headers.get("X-Bridge-Token")
                            or (query.get("token") or [""])[0])
                return secrets.compare_digest(supplied, bridge.token)

            def _body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                if not length:
                    return {}
                try:
                    return json.loads(self.rfile.read(length))
                except json.JSONDecodeError:
                    return {}

            def _session(self, parts: list[str]) -> BridgeSession | None:
                try:
                    return bridge.sessions[int(parts[2])]
                except (KeyError, ValueError, IndexError):
                    return None

            # -- routing --
            def do_GET(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                parts = [p for p in url.path.split("/") if p]

                if url.path in ("/", "/index.html"):
                    if not self._authorized(query):
                        return self._send(403, {"error": "bad token"})
                    if UI_PATH.is_file():
                        return self._send(
                            200, UI_PATH.read_bytes(),
                            "text/html; charset=utf-8")
                    return self._send(200, b"<h1>UI file missing</h1>",
                                      "text/html; charset=utf-8")

                if not self._authorized(query):
                    return self._send(403, {"error": "bad token"})

                if parts == ["api", "sessions"]:
                    return self._send(200, bridge.list_sessions())
                if (len(parts) == 4 and parts[:2] == ["api", "sessions"]
                        and parts[3] == "state"):
                    session = self._session(parts)
                    if session is None:
                        return self._send(404, {"error": "no such session"})
                    return self._send(200, session.state())
                if parts == ["api", "health"]:
                    rows = summarize_health(project_root=str(bridge.root))
                    return self._send(200, {"rows": rows,
                                            "text": format_health(rows)})
                if parts == ["api", "orchestrator"]:
                    from harness.process_orchestrator import max_processes
                    open_sessions = [s for s in bridge.sessions.values()
                                     if not s.closed]
                    return self._send(200, {
                        "cpu_count": __import__("os").cpu_count(),
                        "max_processes": max_processes(),
                        "open_sessions": len(open_sessions),
                        "available": max(0, max_processes()
                                         - len(open_sessions)),
                    })
                return self._send(404, {"error": "not found"})

            def do_POST(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if not self._authorized(query):
                    return self._send(403, {"error": "bad token"})
                parts = [p for p in url.path.split("/") if p]
                body = self._body()

                if parts == ["api", "sessions"]:
                    mode = body.get("mode", DEFAULT_MODE)
                    result = self.server_create(mode)
                    return self._send(200, result)
                if parts == ["api", "orchestrator", "max_sessions"]:
                    from harness.process_orchestrator import max_processes
                    mode = body.get("mode", DEFAULT_MODE)
                    open_count = len([s for s in bridge.sessions.values()
                                      if not s.closed])
                    created = []
                    for _ in range(max(0, max_processes() - open_count)):
                        state = bridge.create_session(mode)
                        if "error" in state:
                            break
                        created.append(state["id"])
                    return self._send(200, {"created": created,
                                            "max": max_processes()})
                if len(parts) == 4 and parts[:2] == ["api", "sessions"]:
                    session = self._session(parts)
                    if session is None:
                        return self._send(404, {"error": "no such session"})
                    action = parts[3]
                    if action == "input":
                        return self._send(
                            200, session.feed(str(body.get("line", ""))))
                    if action == "decision":
                        return self._send(
                            200, session.decide(bool(body.get("approve"))))
                    if action == "close":
                        return self._send(200, session.close())
                return self._send(404, {"error": "not found"})

            def server_create(self, mode):
                return bridge.create_session(mode)

        return ThreadingHTTPServer((host, port), Handler)

    def shutdown_sessions(self) -> None:
        for session in self.sessions.values():
            session.close()


def serve(root: str | Path = ".", host: str = "127.0.0.1", port: int = 4175,
          token: str | None = None, open_browser: bool = False) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    bridge = DesktopBridge(root=root, token=token)
    server = bridge.make_server(host, port)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/?token={bridge.token}"
    print(f"surfing_ai desktop bridge: {url}")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.shutdown_sessions()
        server.server_close()
