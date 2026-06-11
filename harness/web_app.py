"""Dependency-free local Surfing AI agent console."""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .chat_agent import ChatAgent
from .context_reducer import reduce_context
from .coupled_approval_guard import CoupledApprovalState, evaluate
from .multi_agent import build_orchestration_plan, runtime_catalog
from .public_release_guard import run_release_check
from .reduction_audit import audit_reduction
from .release_package import archive_filename, build_release_bytes
from .router import choose_route
from .safety_barrier import scan_command
from .trace import TraceStore
from .validator import VerifierGate

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"


class WebAppService:
    """JSON-friendly facade over the harness's deterministic APIs."""

    def __init__(self, project_root: str | Path = ROOT):
        self.project_root = Path(project_root).resolve()
        self.trace = TraceStore()
        self.chat_agent = ChatAgent(self.project_root)

    def chat(self, payload: dict) -> dict:
        result = self.chat_agent.chat(payload.get("messages"))
        self.trace.record("chat", "chat_agent", mode=result["mode"],
                          model=result.get("model"))
        return result

    def analyze(self, payload: dict) -> dict:
        goal = str(payload.get("goal", "")).strip()
        context = str(payload.get("context", ""))
        if not goal:
            raise ValueError("goal is required")

        state = reduce_context(context, goal)
        criteria = payload.get("success_criteria", [])
        if isinstance(criteria, list):
            state.success_criteria = [
                str(item).strip() for item in criteria if str(item).strip()
            ]

        audit = audit_reduction(context, state, choose_route)
        route = choose_route(state)
        self.trace.record(
            state.task_id,
            "context_reducer",
            task_type=state.task_type,
            risk_level=state.risk_level,
        )
        self.trace.record(
            state.task_id,
            "reduction_audit",
            status=audit.status,
            missing_fields=audit.missing_fields,
        )
        self.trace.record(state.task_id, "router", route=route)

        return {
            "task": state.to_dict(),
            "audit": {
                "status": audit.status,
                "passed": audit.passed,
                "missing_fields": audit.missing_fields,
                "guidance": audit.guidance,
            },
            "route": route,
            "trace": self.trace.for_task(state.task_id),
        }

    def orchestrate(self, payload: dict) -> dict:
        providers = payload.get("providers")
        if providers is not None and not isinstance(providers, list):
            raise ValueError("providers must be a list")
        return build_orchestration_plan(
            goal=str(payload.get("goal", "")),
            context=str(payload.get("context", "")),
            providers=providers,
        )

    def scan_command(self, payload: dict) -> dict:
        command = str(payload.get("command", "")).strip()
        if not command:
            raise ValueError("command is required")
        scan = scan_command(command)
        return {
            "command": command,
            "blocked": scan.blocked,
            "reasons": scan.reasons,
            "warnings": scan.warnings,
            "risk_score": scan.risk_score,
        }

    def verify(self, payload: dict) -> dict:
        task_data = payload.get("task")
        if not isinstance(task_data, dict):
            raise ValueError("task is required")
        from .state import TaskState

        state = TaskState.from_dict(task_data)
        outcome = payload.get("outcome", {})
        if not isinstance(outcome, dict):
            raise ValueError("outcome must be an object")
        judgment = VerifierGate().verify(state, outcome)
        self.trace.record(
            state.task_id,
            "verifier",
            approved=judgment.approved,
            reasons=judgment.reasons,
        )
        return {
            "approved": judgment.approved,
            "reasons": judgment.reasons,
            "needs_human": judgment.needs_human,
            "trace": self.trace.for_task(state.task_id),
        }

    def approval(self, payload: dict) -> dict:
        action_type = str(payload.get("action_type", "")).strip()
        if not action_type:
            raise ValueError("action_type is required")
        approval_state = CoupledApprovalState(
            human_intent=payload.get("human_intent"),
            ai_proposal=str(payload.get("ai_proposal", "")),
            verifier_approved=bool(payload.get("verifier_approved", False)),
            rollback_ref=payload.get("rollback_ref"),
        )
        action_payload = payload.get("payload", {})
        if not isinstance(action_payload, dict):
            raise ValueError("payload must be an object")
        decision = evaluate(action_type, action_payload, approval_state)
        return {
            "approved": decision.approved,
            "status": decision.status,
            "reasons": decision.reasons,
            "worst_case": asdict(decision.worst_case),
        }

    def release_scan(self, payload: dict) -> dict:
        approved = bool(payload.get("user_approved", False))
        report = run_release_check(self.project_root, user_approved=approved)
        return {
            "status": report.status,
            "passed": report.passed,
            "secret_findings": report.secret_findings,
            "notes": report.notes,
            "leak_findings": _report_findings(report.leak_report),
            "scrape_findings": _report_findings(report.scrape_report),
        }


def _report_findings(report: object) -> list[str]:
    if report is None:
        return []
    findings = getattr(report, "findings", [])
    return [str(item) for item in findings]


class HarnessRequestHandler(BaseHTTPRequestHandler):
    service = WebAppService()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(
                {
                    "ok": True,
                    "service": "surfing-ai",
                    "version": __version__,
                    "features": ["chat", "fleet", "analyze", "command",
                                 "approval", "release"],
                    "runtimes": [item["key"] for item in runtime_catalog()],
                }
            )
            return
        if path == "/api/runtimes":
            self._send_json({"runtimes": runtime_catalog()})
            return
        if path in ("/download/surfing-ai.zip", "/download/harness.zip"):
            self._send_download()
            return
        if path == "/":
            self._send_file(WEB_ROOT / "index.html")
            return
        if path in ("/app", "/app/"):
            self._send_file(WEB_ROOT / "app.html")
            return
        if path.startswith("/static/"):
            relative = path.removeprefix("/static/")
            self._send_static(relative)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        routes = {
            "/api/chat": self.service.chat,
            "/api/orchestrate": self.service.orchestrate,
            "/api/analyze": self.service.analyze,
            "/api/scan-command": self.service.scan_command,
            "/api/verify": self.service.verify,
            "/api/approval": self.service.approval,
            "/api/release-scan": self.service.release_scan,
        }
        handler = routes.get(urlparse(self.path).path)
        if handler is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            self._send_json(handler(payload))
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json(
                {"error": f"request failed: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(
        self, payload: dict, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_download(self) -> None:
        body = build_release_bytes(ROOT)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{archive_filename(ROOT)}"',
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, relative: str) -> None:
        candidate = (WEB_ROOT / relative).resolve()
        if not candidate.is_relative_to(WEB_ROOT.resolve()):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self._send_file(candidate)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "application/json",
        ):
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        print(f"[web] {self.address_string()} - {format % args}")


def serve(
    host: str = "127.0.0.1",
    port: int = 4173,
    project_root: str | Path = ROOT,
) -> None:
    handler = type(
        "ConfiguredHarnessRequestHandler",
        (HarnessRequestHandler,),
        {"service": WebAppService(project_root)},
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Surfing AI: http://{host}:{port}")
    print(f"Agent console: http://{host}:{port}/app")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--project-root", default=str(ROOT))
    parser.add_argument(
        "--open",
        action="store_true",
        help="open the local website in the default browser",
    )
    args = parser.parse_args()
    if args.open:
        url = f"http://{args.host}:{args.port}/"
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    serve(args.host, args.port, args.project_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
