"""JSONL approval queue for terminal private mode.

Append-only JSONL file; the current state of each request is the last
record written for its id. Used for external-prompt approvals and any
other action that needs an explicit human decision.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"


class ApprovalQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ---- storage ---------------------------------------------------------

    def _append(self, record: dict) -> dict:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str)
                     + "\n")
        return record

    def _fold(self) -> dict[int, dict]:
        state: dict[int, dict] = {}
        if not self.path.is_file():
            return state
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            state[int(record["id"])] = record
        return state

    # ---- API -------------------------------------------------------------

    def request(self, kind: str, label: str,
                detail: dict | None = None) -> dict:
        state = self._fold()
        new_id = max(state.keys(), default=0) + 1
        return self._append({
            "id": new_id, "ts": time.time(), "kind": kind, "label": label,
            "status": PENDING, "detail": detail or {},
        })

    def get(self, request_id: int) -> dict:
        state = self._fold()
        if request_id not in state:
            raise KeyError(f"no approval request with id {request_id}")
        return state[request_id]

    def list(self, status: str | None = None) -> list[dict]:
        records = sorted(self._fold().values(), key=lambda r: r["id"])
        if status:
            records = [r for r in records if r["status"] == status]
        return records

    def pending(self) -> list[dict]:
        return self.list(PENDING)

    def _decide(self, request_id: int, status: str, reason: str = "") -> dict:
        record = self.get(request_id)
        if record["status"] != PENDING:
            raise ValueError(
                f"request {request_id} already {record['status']}")
        decided = {**record, "status": status, "decided_ts": time.time(),
                   "reason": reason}
        return self._append(decided)

    def approve(self, request_id: int) -> dict:
        return self._decide(request_id, APPROVED)

    def deny(self, request_id: int, reason: str = "") -> dict:
        return self._decide(request_id, DENIED, reason)
