"""User-controllable thread budget.

Reads the host machine's logical thread (CPU) count and converts a
user-chosen utilization level — 20% / 50% / 70% / 100% — into a concrete
worker count for the ParallelRunner / tmux grid / max-procs paths.

Design choices:
- "logical threads" = os.cpu_count(), i.e. hardware threads incl. SMT/
  Hyper-Threading, which is what a user means by "my CPU's threads".
- A level always yields at least 1 worker and never exceeds the total.
- 100% intentionally means *all* threads (no reserve). Lower levels round
  to the nearest worker. This keeps the mapping predictable for the UI.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# The levels the user can pick from (percent of logical threads).
LEVELS: tuple[int, ...] = (20, 50, 60, 70, 80, 90, 100)


def logical_threads() -> int:
    """Hardware threads available to this process (SMT included)."""
    return os.cpu_count() or 2


def workers_for_percent(percent: int, total: int | None = None) -> int:
    """Worker count for a utilization percent, clamped to [1, total]."""
    if percent <= 0:
        raise ValueError("percent must be > 0")
    total = total if total is not None else logical_threads()
    total = max(1, total)
    workers = round(total * percent / 100)
    return max(1, min(total, workers))


def normalize_level(value) -> int:
    """Accept 20 / "20" / "20%" / "max" / "full" -> a percent in LEVELS-ish.

    'max'/'full'/'all' -> 100. Raises ValueError on anything unparseable.
    """
    if isinstance(value, str):
        v = value.strip().lower().rstrip("%")
        if v in ("max", "full", "all"):
            return 100
        if not v.isdigit():
            raise ValueError(f"unrecognized thread level: {value!r}")
        value = int(v)
    value = int(value)
    if value <= 0 or value > 100:
        raise ValueError("thread level must be in (0, 100]")
    return value


def resolve_workers(level, total: int | None = None) -> int:
    """High-level entry: level (20/50/70/100/'max') -> worker count."""
    return workers_for_percent(normalize_level(level), total)


def saved_level(workdir: str | Path) -> int | None:
    """Read a thread_budget.json written by the menu-bar / tray, if any."""
    try:
        data = json.loads(
            (Path(workdir) / "thread_budget.json").read_text())
        percent = int(data.get("percent"))
        return percent if 0 < percent <= 100 else None
    except Exception:
        return None


@dataclass(frozen=True)
class BudgetRow:
    percent: int
    workers: int


def budget_table(total: int | None = None) -> list[BudgetRow]:
    """Preview of every selectable level -> worker count, for UI/CLI."""
    total = total if total is not None else logical_threads()
    return [BudgetRow(p, workers_for_percent(p, total)) for p in LEVELS]


def describe(total: int | None = None) -> dict:
    """JSON-friendly snapshot for the web/desktop bridge."""
    total = total if total is not None else logical_threads()
    return {
        "logical_threads": total,
        "levels": [{"percent": r.percent, "workers": r.workers}
                   for r in budget_table(total)],
        "default_level": 50,
    }


def format_table(total: int | None = None) -> str:
    """Human-readable table for the CLI `threads` command."""
    total = total if total is not None else logical_threads()
    lines = [f"logical threads detected: {total}",
             "", "  level   workers", "  -----   -------"]
    for row in budget_table(total):
        star = "  <- default" if row.percent == 50 else ""
        lines.append(f"  {row.percent:>3}%    {row.workers:>5}{star}")
    return "\n".join(lines)
