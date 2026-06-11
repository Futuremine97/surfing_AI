"""Token budget accounting for harness stages."""

from __future__ import annotations


class BudgetExceeded(RuntimeError):
    pass


def estimate_tokens(text: str | int) -> int:
    """Cheap deterministic token estimate (~4 chars per token)."""
    if isinstance(text, int):
        return max(0, text)
    return max(1, len(text) // 4)


class TokenBudget:
    """Tracks token spend per stage and enforces a hard limit."""

    def __init__(self, limit: int):
        self.limit = limit
        self.spent = 0
        self.ledger: list[tuple[str, int]] = []

    @property
    def remaining(self) -> int:
        return self.limit - self.spent

    def can_afford(self, text: str | int) -> bool:
        return estimate_tokens(text) <= self.remaining

    def charge(self, stage: str, text: str | int) -> int:
        cost = estimate_tokens(text)
        if cost > self.remaining:
            raise BudgetExceeded(
                f"stage '{stage}' needs {cost} tokens, only {self.remaining} left"
            )
        self.spent += cost
        self.ledger.append((stage, cost))
        return cost
