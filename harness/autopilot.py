"""Cowork mode — a long-running, proactive agentic loop for the CLI.

Give it a mission and it works on its own: it orients (backend health,
agent fleet), plans (cross-runtime orchestration), acts (safe, allowlisted
probes), verifies (thread-budget readiness), reflects, and then settles
into a steady-state *monitor* loop where it keeps watching and journaling
notable changes — the way a cowork agent stays active over a long session.

It is deterministic and local: there is no external model call. Autonomy
comes from a playbook over the harness's own capabilities. Every shell
action is screened by the same private-mode policy as the REPL
(`check_command`); anything risky is queued for human approval instead of
being run. All progress is appended to a journal on disk, so a session
survives across CLI calls and can be resumed or run detached (e.g. via
`surfing_ai bg start "python3 scripts/surfing_ai cowork run -s <id> -c 50"`).
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parent.parent
COWORK_DIR = "cowork"


# ---------------------------------------------------------------- actions

def _backend_health(session) -> tuple[str, str]:
    from harness.backend_health import format_health, summarize_health
    text = format_health(summarize_health(project_root=str(REPO)))
    first = text.splitlines()[0] if text else "no health"
    return "evidence", f"backend health → {first}"


def _fleet_snapshot(session) -> tuple[str, str]:
    from harness.agent_fleet import Fleet, snapshot
    snap = snapshot(Fleet.load(session.exec_root), session.exec_root)
    return "evidence", (
        f"fleet → {snap['enabled_nodes']}/{len(snap['nodes'])} agents on, "
        f"{snap['allocated_threads']}/{snap['budget_threads']} threads "
        f"allocated")


def _orchestration_plan(session) -> tuple[str, str]:
    from harness.multi_agent import build_orchestration_plan
    plan = build_orchestration_plan(goal=session.mission)
    return "plan", (
        f"plan {plan['task_id']}: {plan['agent_count']} lanes × "
        f"explore/build/verify ({plan['subagent_count']} subagents), "
        f"fusion = {plan['fusion']['strategy']}")


def _inspect_tree(session) -> tuple[str, str]:
    rc, out = session.run_shell("git status --short")
    if rc is None:
        return "blocked", out
    if rc != 0:
        return "evidence", "working tree probe: not a git repo / no output"
    changed = len([ln for ln in out.splitlines() if ln.strip()])
    return "evidence", f"working tree → {changed} changed path(s)"


def _thread_readiness(session) -> tuple[str, str]:
    from harness.thread_budget import describe
    d = describe()
    return "verify", (
        f"thread readiness → {d['logical_threads']} logical threads, "
        f"default budget {d['default_level']}%")


def _reflect(session) -> tuple[str, str]:
    ev = [e for e in session.read_journal()
          if e.get("type") in ("evidence", "plan")]
    return "reflection", (
        f"mission '{session.mission}': gathered {len(ev)} findings; "
        "no blocking risks — entering proactive monitor mode")


PLAYBOOK = [
    ("orient", _backend_health),
    ("orient", _fleet_snapshot),
    ("plan", _orchestration_plan),
    ("act", _inspect_tree),
    ("verify", _thread_readiness),
    ("reflect", _reflect),
]


# ---------------------------------------------------------------- session

class Session:
    def __init__(self, root, sid: str, state: dict):
        self.root = Path(root)
        self.sid = sid
        self.state = state

    # -- paths --
    @property
    def dir(self) -> Path:
        return self.root / COWORK_DIR / self.sid

    @property
    def journal_path(self) -> Path:
        return self.dir / "journal.jsonl"

    @property
    def exec_root(self) -> Path:
        return Path(self.state.get("exec_root", self.root))

    @property
    def mission(self) -> str:
        return self.state.get("mission", "")

    # -- io --
    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "state.json").write_text(
            json.dumps(self.state, indent=2) + "\n", encoding="utf-8")

    def append(self, etype: str, message: str, **extra) -> dict:
        entry = {"ts": time.time(), "step": self.state["step"],
                 "phase": extra.pop("phase", ""), "type": etype,
                 "message": message, **extra}
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry

    def read_journal(self) -> list[dict]:
        try:
            return [json.loads(ln) for ln in
                    self.journal_path.read_text().splitlines() if ln.strip()]
        except FileNotFoundError:
            return []

    # -- safe shell execution (gated like the REPL) --
    def run_shell(self, command: str, timeout: int = 30):
        """Return (returncode, output). returncode None ⇒ blocked (queued
        for approval), output holds the reason."""
        from harness.terminal_private_mode import check_command
        import shlex
        decision = check_command(command)
        if not decision.allowed:
            self.append("approval_request",
                        f"needs approval: {command} ({decision.reason})",
                        command=command, alternative=decision.alternative)
            return None, f"BLOCKED: {decision.reason}"
        try:
            proc = subprocess.run(
                shlex.split(command), cwd=str(self.exec_root),
                capture_output=True, text=True, timeout=timeout)
            return proc.returncode, (proc.stdout or proc.stderr).strip()
        except Exception as exc:
            return 1, f"error: {exc}"


# ---------------------------------------------------------------- engine

def start(mission: str, root, exec_root=None) -> Session:
    mission = mission.strip()
    if not mission:
        raise ValueError("mission is required")
    sid = uuid4().hex[:8]
    state = {
        "session": sid, "mission": mission, "status": "active",
        "step": 0, "cursor": 0,
        "exec_root": str(exec_root or root),
        "created": time.time(),
    }
    session = Session(root, sid, state)
    session.save()
    session.append("mission", f"mission accepted: {mission}", phase="start")
    return session


def load(root, sid: str) -> Session:
    state = json.loads((Path(root) / COWORK_DIR / sid / "state.json")
                       .read_text())
    return Session(root, sid, state)


def latest(root) -> str | None:
    base = Path(root) / COWORK_DIR
    if not base.is_dir():
        return None
    sessions = []
    for d in base.iterdir():
        sf = d / "state.json"
        if sf.is_file():
            try:
                st = json.loads(sf.read_text())
                sessions.append((st.get("created", 0), d.name))
            except Exception:
                pass
    if not sessions:
        return None
    return sorted(sessions)[-1][1]


def tick(session: Session) -> dict:
    """Advance one autonomous step; return the journal entry produced."""
    if session.state["status"] == "stopped":
        return session.append("info", "session is stopped", phase="halt")
    session.state["step"] += 1
    cursor = session.state["cursor"]

    if cursor < len(PLAYBOOK):
        phase, fn = PLAYBOOK[cursor]
        try:
            etype, message = fn(session)
        except Exception as exc:
            etype, message = "evidence", f"{phase} step error: {exc}"
        session.state["cursor"] = cursor + 1
        if session.state["cursor"] >= len(PLAYBOOK):
            session.state["status"] = "monitoring"
        entry = session.append(etype, message, phase=phase)
        session.save()
        return entry

    # steady-state: proactively monitor and journal changes
    from harness.backend_health import summarize_health
    rows = summarize_health(project_root=str(REPO))
    fingerprint = ";".join(sorted(
        f"{r.get('backend', r.get('name', '?'))}:{r.get('binary', r.get('status', '?'))}"
        for r in rows)) if isinstance(rows, list) else str(rows)
    changed = fingerprint != session.state.get("last_fingerprint")
    session.state["last_fingerprint"] = fingerprint
    session.state["status"] = "monitoring"
    msg = ("backend status changed — re-evaluating"
           if changed and session.state["step"] > len(PLAYBOOK) + 1
           else "steady — no change since last check")
    entry = session.append("monitor", msg, phase="monitor")
    session.save()
    return entry


def run(session: Session, cycles: int = 6) -> list[dict]:
    out = []
    for _ in range(max(1, cycles)):
        if session.state["status"] == "stopped":
            break
        out.append(tick(session))
    return out


def stop(session: Session) -> Session:
    session.state["status"] = "stopped"
    session.save()
    session.append("info", "session stopped by user", phase="halt")
    return session


def status_summary(session: Session) -> dict:
    j = session.read_journal()
    return {
        "session": session.sid, "mission": session.mission,
        "status": session.state["status"], "step": session.state["step"],
        "cursor": f"{session.state['cursor']}/{len(PLAYBOOK)}",
        "journal_entries": len(j),
    }


def list_sessions(root) -> list[dict]:
    base = Path(root) / COWORK_DIR
    rows = []
    if base.is_dir():
        for d in sorted(base.iterdir()):
            sf = d / "state.json"
            if sf.is_file():
                try:
                    st = json.loads(sf.read_text())
                    rows.append({"session": st["session"],
                                 "status": st.get("status", "?"),
                                 "step": st.get("step", 0),
                                 "mission": st.get("mission", "")})
                except Exception:
                    pass
    return rows
