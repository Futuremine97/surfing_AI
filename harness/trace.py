"""Append-only trace store for every harness decision."""

from __future__ import annotations

import json
import time
from pathlib import Path


class TraceStore:
    """Records structured events; optionally persists to a JSONL file."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.events: list[dict] = []

    def record(self, task_id: str, stage: str, **payload) -> dict:
        event = {
            "ts": time.time(),
            "task_id": task_id,
            "stage": stage,
            **payload,
        }
        self.events.append(event)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return event

    def for_task(self, task_id: str) -> list[dict]:
        return [e for e in self.events if e["task_id"] == task_id]
