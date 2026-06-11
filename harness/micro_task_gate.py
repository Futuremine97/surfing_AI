"""Micro-task gate: decides what may be delegated to small agents and
enforces the small-agent policy (no writes, no shell, no network, no
private artifacts unless explicitly in private mode)."""

from __future__ import annotations

from .private_leak_guard import load_blocklist, scan_text
from .state import TaskState


class MicroTaskPolicyError(RuntimeError):
    pass


MICRO_TASK_TYPES = {"micro", "question", "extract", "classify", "summarize", "validate"}

FORBIDDEN_PAYLOAD_KEYS = {"write_file", "shell", "network", "url", "exec"}


def is_micro_task(task: TaskState) -> bool:
    """A task is micro when it is low risk, needs no side effects, and is a
    pure text transformation."""
    return (
        task.risk_level == "low"
        and not task.needs_code_edit
        and not task.needs_shell
        and not task.needs_human_approval
        and not task.public_release_requested
        and task.task_type in MICRO_TASK_TYPES
    )


def guard_payload(payload, private_mode: bool = False,
                  blocklist: list[str] | None = None) -> None:
    """Reject payloads that ask for side effects or carry private artifacts."""
    if isinstance(payload, dict):
        bad = FORBIDDEN_PAYLOAD_KEYS & set(payload)
        if bad:
            raise MicroTaskPolicyError(
                f"small agents cannot perform side effects: {sorted(bad)}"
            )
        text = " ".join(str(v) for v in payload.values())
    else:
        text = str(payload)

    if not private_mode:
        terms = blocklist if blocklist is not None else load_blocklist().terms
        findings = scan_text(text, terms)
        if findings:
            raise MicroTaskPolicyError(
                "payload contains restricted internal terms; "
                "small agents may not receive private artifacts"
            )
