"""Backend health for private mode: reuses backend_doctor but restricts
every reported value to a safe vocabulary, so health output can never
leak paths, versions, usernames, or credential details.

Safe vocabulary: present / missing / ok / failed / not_configured.
"""

from __future__ import annotations

SAFE_VOCAB = {"present", "missing", "ok", "failed", "not_configured"}


def summarize_health(statuses: list[dict] | None = None,
                     project_root: str = ".") -> list[dict]:
    """Reduce backend_doctor.diagnose() output to safe vocabulary only.

    `statuses` may be injected for tests; otherwise diagnose() runs.
    """
    if statuses is None:
        from harness.backend_doctor import diagnose
        statuses = diagnose(project_root=project_root)

    rows = []
    for status in statuses:
        installed = bool(status.get("installed"))
        authenticated = status.get("authenticated")
        if not installed or authenticated is None:
            auth = "not_configured"
        else:
            auth = "ok" if authenticated else "failed"
        rows.append({
            "backend": str(status.get("backend", "unknown")),
            "binary": "present" if installed else "missing",
            "auth": auth,
            "api_key": "present" if status.get("key_present") else "missing",
        })
    return rows


def format_health(rows: list[dict]) -> str:
    lines = ["backend health (safe vocabulary only)"]
    for row in rows:
        lines.append(f"  {row['backend']}: binary={row['binary']} "
                     f"auth={row['auth']} api_key={row['api_key']}")
    return "\n".join(lines)
