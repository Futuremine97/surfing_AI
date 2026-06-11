"""Compact task state used for routing and verification."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field

RISK_LEVELS = ("low", "medium", "high")
LEAK_RISK_LEVELS = ("none", "low", "high")


@dataclass
class TaskState:
    """The compact task state distilled from raw context.

    All routing, verification, and budgeting decisions read this object
    instead of the raw context, keeping expensive-model calls small.
    """

    task_id: str
    user_goal: str
    task_type: str = "general"
    compact_summary: str = ""
    success_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    current_error: str | None = None
    relevant_files: list[str] = field(default_factory=list)
    relevant_commands: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    risk_level: str = "low"
    needs_code_edit: bool = False
    needs_shell: bool = False
    needs_human_approval: bool = False
    token_budget: int = 8000
    public_release_requested: bool = False
    private_research_leak_risk: str = "none"

    def __post_init__(self) -> None:
        if self.risk_level not in RISK_LEVELS:
            raise ValueError(f"risk_level must be one of {RISK_LEVELS}")
        if self.private_research_leak_risk not in LEAK_RISK_LEVELS:
            raise ValueError(
                f"private_research_leak_risk must be one of {LEAK_RISK_LEVELS}"
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskState":
        return cls(**data)

    @classmethod
    def new(cls, user_goal: str, **kwargs) -> "TaskState":
        return cls(task_id=uuid.uuid4().hex[:12], user_goal=user_goal, **kwargs)
