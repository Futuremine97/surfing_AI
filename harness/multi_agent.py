"""Cross-runtime planning for parallel agent and subagent work."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4


@dataclass(frozen=True)
class RuntimeSpec:
    key: str
    label: str
    accent: str
    project_config: str
    install_command: str
    launch_hint: str
    subagent_model: str
    nesting: str


RUNTIMES = {
    "antigravity": RuntimeSpec(
        key="antigravity",
        label="Antigravity",
        accent="#48e5ff",
        project_config=".agents/",
        install_command="agy plugin install integrations/antigravity",
        launch_hint="Run /surfing-team or ask the parent to invoke subagents.",
        subagent_model="Asynchronous invoke_subagent sessions",
        nesting="Custom subagents may delegate up to 10 levels.",
    ),
    "codex": RuntimeSpec(
        key="codex",
        label="Codex",
        accent="#7c6cff",
        project_config=".codex/config.toml + AGENTS.md",
        install_command="codex",
        launch_hint="Use $surfing-team or ask Codex to delegate in parallel.",
        subagent_model="Multi-agent roles from .codex/config.toml",
        nesting="Subagents inherit the active sandbox policy.",
    ),
    "claude": RuntimeSpec(
        key="claude",
        label="Claude",
        accent="#ff8f70",
        project_config=".claude-plugin/ + agents/",
        install_command=(
            "claude plugin install "
            "verification-gated-harness@futuremine97-tools"
        ),
        launch_hint=(
            "Run /verification-gated-harness:route-and-verify and delegate "
            "to plugin agents."
        ),
        subagent_model="Project or plugin subagents",
        nesting="Claude subagents report to the parent and do not nest.",
    ),
}

SUBAGENT_ROLES = (
    (
        "explorer",
        "Map the relevant code, constraints, dependencies, and failure signals.",
        "read-only",
    ),
    (
        "builder",
        "Implement the smallest complete change that satisfies the goal.",
        "workspace-write",
    ),
    (
        "verifier",
        "Review the implementation and collect independent test evidence.",
        "read-only",
    ),
)


def runtime_catalog() -> list[dict]:
    """Return browser-friendly metadata for all supported runtimes."""
    return [asdict(spec) for spec in RUNTIMES.values()]


def build_orchestration_plan(
    goal: str,
    context: str = "",
    providers: list[str] | None = None,
) -> dict:
    """Create a deterministic parallel plan without invoking external CLIs."""
    goal = str(goal).strip()
    if not goal:
        raise ValueError("goal is required")

    requested = providers or list(RUNTIMES)
    selected: list[str] = []
    for provider in requested:
        key = str(provider).strip().lower()
        if key not in RUNTIMES:
            raise ValueError(f"unsupported provider: {provider}")
        if key not in selected:
            selected.append(key)
    if not selected:
        raise ValueError("at least one provider is required")

    task_id = f"surf-{uuid4().hex[:10]}"
    context_hint = _context_hint(context)
    lanes = []
    for provider in selected:
        spec = RUNTIMES[provider]
        subagents = []
        for index, (role, objective, access) in enumerate(
            SUBAGENT_ROLES, start=1
        ):
            subagents.append({
                "id": f"{provider}-{role}-{index}",
                "role": role,
                "objective": f"{objective} Goal: {goal}",
                "access": access,
                "wave": 2,
                "status": "queued",
            })

        lanes.append({
            "runtime": provider,
            "label": spec.label,
            "accent": spec.accent,
            "status": "ready",
            "parent": {
                "id": f"{provider}-parent",
                "role": "coordinator",
                "objective": (
                    f"Own the {spec.label} lane, dispatch independent work, "
                    "and return a concise evidence-backed recommendation."
                ),
                "wave": 1,
            },
            "subagents": subagents,
            "launch_hint": spec.launch_hint,
            "constraint": spec.nesting,
        })

    return {
        "task_id": task_id,
        "goal": goal,
        "context_hint": context_hint,
        "mode": "parallel",
        "provider_count": len(lanes),
        "agent_count": len(lanes),
        "subagent_count": len(lanes) * len(SUBAGENT_ROLES),
        "waves": [
            {
                "number": 1,
                "name": "Dispatch",
                "description": "Start every runtime coordinator concurrently.",
            },
            {
                "number": 2,
                "name": "Explore, build, verify",
                "description": (
                    "Run role-isolated subagents in parallel inside each lane."
                ),
            },
            {
                "number": 3,
                "name": "Evidence fusion",
                "description": (
                    "Compare recommendations and advance only verified output."
                ),
            },
        ],
        "lanes": lanes,
        "fusion": {
            "strategy": "verification-weighted consensus",
            "minimum_evidence": [
                "implementation summary",
                "test or inspection result",
                "known risks",
            ],
            "human_gate": (
                "Required for destructive, publish, marketplace, or "
                "visibility-changing actions."
            ),
        },
        "execution": {
            "status": "plan_ready",
            "note": (
                "Surfing AI prepares native runtime instructions and never "
                "silently starts external agent CLIs from the browser."
            ),
        },
    }


def _context_hint(context: str) -> str:
    cleaned = " ".join(str(context).split())
    if not cleaned:
        return "No extra context supplied."
    if len(cleaned) <= 180:
        return cleaned
    return cleaned[:177].rstrip() + "..."
