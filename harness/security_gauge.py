"""Security Gauge — 5-level model-access and routing-freedom controller.

Level semantics
---------------
0  LOCKED      No external model calls. Local-only mode enforced.
1  MINIMAL     Local tools only. No external API.
2  CAUTIOUS    Small external models (haiku, gpt-3.5). Redacted + explicit approval.
3  STANDARD    Larger models (sonnet, gpt-4). Audited external calls.
4  MAXIMUM     All models including most capable. Full routing freedom.

GaugeState
----------
  level         : int     0-4     current security clearance
  needle        : float   0.0-1.0 visual needle within the current level band
  locked_levels : list[int]       levels whose lock button has been engaged

The needle drives drag-based UI interactivity. When the needle reaches 0.0 or
1.0 the level steps down/up accordingly (unless locked). The discrete level is
the actual security gatekeeper — the needle is purely a visual affordance.

Persistence: <project_root>/.surfing_ai_security_gauge.json (gitignored).
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

GAUGE_FILE = ".surfing_ai_security_gauge.json"

# ── per-level definitions ────────────────────────────────────────────────────

LEVEL_DEFS: list[dict[str, Any]] = [
    {
        "level": 0,
        "name": "LOCKED",
        "color": "#f85149",
        "description": "No external calls. Local-only mode enforced.",
        "allowed_models": [],
        "allowed_routes": ["command_risk_scan", "shell_tool"],
        "external_allowed": False,
        "redact_required": True,
        "approval_required": True,
        "max_risk_score": 0,
    },
    {
        "level": 1,
        "name": "MINIMAL",
        "color": "#d29922",
        "description": "Local tools only. No external model API calls.",
        "allowed_models": ["local"],
        "allowed_routes": [
            "command_risk_scan", "shell_tool",
            "small_agent", "context_reducer",
        ],
        "external_allowed": False,
        "redact_required": True,
        "approval_required": True,
        "max_risk_score": 2,
    },
    {
        "level": 2,
        "name": "CAUTIOUS",
        "color": "#e3b341",
        "description": "Small models (haiku, gpt-3.5). Redacted + explicit approval.",
        "allowed_models": [
            "claude-haiku-4-5-20251001",
            "gpt-3.5-turbo",
            "gemini-flash",
        ],
        "allowed_routes": [
            "command_risk_scan", "shell_tool",
            "small_agent", "context_reducer", "planner",
        ],
        "external_allowed": True,
        "redact_required": True,
        "approval_required": True,
        "max_risk_score": 4,
    },
    {
        "level": 3,
        "name": "STANDARD",
        "color": "#58a6ff",
        "description": "Larger models (sonnet, gpt-4). Audited external calls.",
        "allowed_models": [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-6",
            "gpt-3.5-turbo",
            "gpt-4",
            "gemini-flash",
            "gemini-pro",
        ],
        "allowed_routes": [
            "command_risk_scan", "shell_tool",
            "small_agent", "context_reducer", "planner",
            "coding_agent", "test_runner", "verifier",
        ],
        "external_allowed": True,
        "redact_required": False,
        "approval_required": False,
        "max_risk_score": 7,
    },
    {
        "level": 4,
        "name": "MAXIMUM",
        "color": "#3fb950",
        "description": "All models including most capable. Full routing freedom.",
        "allowed_models": [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-6",
            "claude-opus-4-8",
            "claude-fable-5",
            "gpt-3.5-turbo",
            "gpt-4",
            "gpt-4o",
            "gemini-flash",
            "gemini-pro",
            "gemini-ultra",
            "o1",
            "o3",
        ],
        "allowed_routes": None,   # None = all routes permitted
        "external_allowed": True,
        "redact_required": False,
        "approval_required": False,
        "max_risk_score": 10,
    },
]

# ── state dataclass ──────────────────────────────────────────────────────────


@dataclass
class GaugeState:
    level: int = 0
    needle: float = 0.0          # 0.0-1.0 within current level band
    locked_levels: list = field(default_factory=list)

    def clamp(self) -> "GaugeState":
        self.level = max(0, min(4, int(self.level)))
        self.needle = max(0.0, min(1.0, float(self.needle)))
        return self

    def to_dict(self) -> dict:
        d = asdict(self)
        d["definition"] = LEVEL_DEFS[self.level]
        return d


# ── main class ───────────────────────────────────────────────────────────────


class SecurityGauge:
    """Thread-safe security gauge with disk persistence."""

    def __init__(self, project_root: str | Path = "."):
        self.root = Path(project_root).resolve()
        self._path = self.root / GAUGE_FILE
        self._lock = threading.Lock()
        self._state = self._load()

    # ── persistence ─────────────────────────────────────────────────────────

    def _load(self) -> GaugeState:
        if self._path.is_file():
            try:
                data = json.loads(self._path.read_text("utf-8"))
                state = GaugeState(
                    level=int(data.get("level", 0)),
                    needle=float(data.get("needle", 0.0)),
                    locked_levels=[int(x) for x in data.get("locked_levels", [])],
                )
                return state.clamp()
            except Exception:
                pass
        return GaugeState()

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(asdict(self._state), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ── public API ───────────────────────────────────────────────────────────

    def get(self) -> GaugeState:
        with self._lock:
            s = self._state
            return GaugeState(level=s.level, needle=s.needle,
                              locked_levels=list(s.locked_levels))

    def set_level(self, level: int, needle: float = 0.0) -> dict:
        """Raise or lower the active security level.
        Returns error dict if the target level is locked or above a lock
        ceiling.
        """
        with self._lock:
            level = max(0, min(4, int(level)))
            # cannot enter a locked level
            if level in self._state.locked_levels:
                return {"error": f"level {level} is locked",
                        "level": self._state.level}
            # cannot raise above any locked level that sits below target
            ceilings = [l for l in self._state.locked_levels if l < level]
            if ceilings:
                ceiling = min(ceilings)
                return {"error": f"blocked by lock at level {ceiling}",
                        "level": self._state.level}
            self._state.level = level
            self._state.needle = max(0.0, min(1.0, float(needle)))
            self._save()
            return self._state.to_dict()

    def set_needle(self, needle: float) -> dict:
        """Move the needle within the current level band.
        Clamped to [0.0, 1.0]; crossing boundaries does NOT auto-step levels
        (that is intentional UX: only the explicit set_level call changes
        level).
        """
        with self._lock:
            self._state.needle = max(0.0, min(1.0, float(needle)))
            self._save()
            return self._state.to_dict()

    def lock_level(self, level: int) -> dict:
        """Lock a level so it cannot be entered."""
        with self._lock:
            level = max(0, min(4, int(level)))
            if level not in self._state.locked_levels:
                self._state.locked_levels.append(level)
                self._state.locked_levels.sort()
            # if current level is now locked, drop to highest accessible below
            if self._state.level in self._state.locked_levels:
                dropped = False
                for l in range(self._state.level - 1, -1, -1):
                    if l not in self._state.locked_levels:
                        self._state.level = l
                        self._state.needle = 0.0
                        dropped = True
                        break
                if not dropped:
                    self._state.level = 0
                    self._state.needle = 0.0
            self._save()
            return self._state.to_dict()

    def unlock_level(self, level: int) -> dict:
        """Remove the lock from a level."""
        with self._lock:
            level = max(0, min(4, int(level)))
            self._state.locked_levels = [
                l for l in self._state.locked_levels if l != level
            ]
            self._save()
            return self._state.to_dict()

    def listing(self) -> dict:
        """Full gauge state suitable for API JSON response."""
        with self._lock:
            s = self._state
            defn = LEVEL_DEFS[s.level]
            return {
                "level": s.level,
                "needle": s.needle,
                "locked_levels": list(s.locked_levels),
                "current": defn,
                "levels": LEVEL_DEFS,
                "allowed_models": defn["allowed_models"],
                "external_allowed": defn["external_allowed"],
                "redact_required": defn["redact_required"],
                "approval_required": defn["approval_required"],
            }

    # ── policy helpers ───────────────────────────────────────────────────────

    def is_model_allowed(self, model: str) -> bool:
        with self._lock:
            allowed = LEVEL_DEFS[self._state.level]["allowed_models"]
            if allowed is None:
                return True
            if not allowed:      # empty list at level 0 = nothing allowed
                return False
            return model in allowed

    def is_route_allowed(self, route: str) -> bool:
        with self._lock:
            allowed = LEVEL_DEFS[self._state.level]["allowed_routes"]
            if allowed is None:
                return True
            return route in allowed

    def is_external_allowed(self) -> bool:
        with self._lock:
            return LEVEL_DEFS[self._state.level]["external_allowed"]

    def filter_routes(self, routes: list[str]) -> list[str]:
        """Remove routes that are not permitted at the current level."""
        with self._lock:
            allowed = LEVEL_DEFS[self._state.level]["allowed_routes"]
            if allowed is None:
                return routes
            return [r for r in routes if r in allowed]
