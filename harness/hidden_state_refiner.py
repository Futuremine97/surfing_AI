"""Hidden-state refiner: when failures repeat or evidence contradicts the
plan, hypothesize the unobserved cause and propose a cheap probe."""

from __future__ import annotations

from dataclasses import dataclass

from .state import TaskState


@dataclass
class Hypothesis:
    cause: str
    probe: str
    signal: str


_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("modulenotfounderror", "importerror", "no module named"),
     "missing dependency", "list installed packages; install the missing one"),
    (("no such file", "enoent", "filenotfound", "not found"),
     "wrong file path", "list the directory; confirm the expected path exists"),
    (("cache", "stale"),
     "stale cache", "clear the relevant cache and retry once"),
    (("401", "403", "timeout", "connection refused", "unreachable", "rate limit"),
     "external API unavailable", "check connectivity/credentials; retry with backoff"),
    (("permission denied", "not permitted"),
     "platform limitation", "check sandbox/platform restrictions before retrying"),
]


def should_invoke(failure_history: list[str],
                  contradiction: bool = False,
                  low_confidence: bool = False) -> bool:
    """Invoke when the same failure repeats, evidence contradicts the plan,
    or router confidence is low."""
    repeats = len(failure_history) >= 2 and (
        len(set(failure_history)) < len(failure_history)
    )
    return repeats or contradiction or low_confidence or len(failure_history) >= 3


def analyze(failure_history: list[str], state: TaskState) -> list[Hypothesis]:
    text = " ".join(failure_history).lower()
    hypotheses = [
        Hypothesis(cause=cause, probe=probe, signal=kw)
        for kws, cause, probe in _RULES
        for kw in kws if kw in text
    ]
    if not hypotheses:
        hypotheses.append(Hypothesis(
            cause="user intent mismatch",
            probe="restate the goal back to the user and confirm success criteria",
            signal="repeated failure with no recognized error signature",
        ))
    # Deduplicate by cause, keep first probe.
    seen: dict[str, Hypothesis] = {}
    for h in hypotheses:
        seen.setdefault(h.cause, h)
    return list(seen.values())
