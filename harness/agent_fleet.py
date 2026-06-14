"""Agent fleet: graphical, controllable view of the running agents and
subagents and how dynamically they hold the machine's threads.

The fleet mirrors the orchestration model in `multi_agent.py`: one lane
per runtime (Antigravity / Codex / Claude), each lane a coordinator plus
explorer / builder / verifier subagents. Every node can be switched on or
off and weighted; the enabled nodes share the current thread budget
(`thread_budget.py`) proportionally to their weight. A live utilization
sampler shows how many of each node's threads are active at any moment.

Nothing here spawns real processes — it is the control-plane model and
its ANSI renderer for the CLI (`surfing_ai fleet`). The same snapshot is
JSON-serializable for the web / desktop frontends.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

from harness.multi_agent import RUNTIMES, SUBAGENT_ROLES
from harness.thread_budget import logical_threads, resolve_workers, saved_level

# role -> default weight (builder is the heaviest worker; coordinator light)
ROLE_WEIGHTS = {
    "coordinator": 1,
    "explorer": 2,
    "builder": 3,
    "verifier": 2,
}
ROLE_GLYPH = {
    "coordinator": "◆",   # ◆
    "explorer": "○",      # ○
    "builder": "■",       # ■
    "verifier": "◇",      # ◇
}
# runtime -> ANSI-256 color
RUNTIME_COLOR = {"antigravity": 45, "codex": 99, "claude": 208}

STATE_FILE = "fleet_state.json"

# block characters for the thread map
_FULL = "█"   # █ active
_HALF = "▒"   # ▒ allocated, idle
_DOT = "·"    # · unallocated


@dataclass
class AgentNode:
    key: str
    runtime: str
    role: str
    label: str
    weight: int
    enabled: bool = True

    @property
    def color(self) -> int:
        return RUNTIME_COLOR.get(self.runtime, 250)

    @property
    def glyph(self) -> str:
        return ROLE_GLYPH.get(self.role, "●")


@dataclass
class Fleet:
    nodes: list[AgentNode] = field(default_factory=list)

    # ---- construction / persistence ----
    @classmethod
    def default(cls) -> "Fleet":
        nodes: list[AgentNode] = []
        for rkey, spec in RUNTIMES.items():
            nodes.append(AgentNode(
                key=f"{rkey}-coordinator", runtime=rkey, role="coordinator",
                label=f"{spec.label} · coordinator",
                weight=ROLE_WEIGHTS["coordinator"]))
            for role, _obj, _access in SUBAGENT_ROLES:
                nodes.append(AgentNode(
                    key=f"{rkey}-{role}", runtime=rkey, role=role,
                    label=f"{spec.label} · {role}",
                    weight=ROLE_WEIGHTS.get(role, 1)))
        return cls(nodes)

    @classmethod
    def load(cls, root: str | Path) -> "Fleet":
        fleet = cls.default()
        try:
            data = json.loads((Path(root) / STATE_FILE).read_text())
        except Exception:
            return fleet
        disabled = set(data.get("disabled", []))
        weights = data.get("weights", {})
        for node in fleet.nodes:
            if node.key in disabled:
                node.enabled = False
            if node.key in weights:
                try:
                    node.weight = max(0, int(weights[node.key]))
                except (TypeError, ValueError):
                    pass
        return fleet

    def save(self, root: str | Path) -> Path:
        path = Path(root) / STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "disabled": [n.key for n in self.nodes if not n.enabled],
            "weights": {n.key: n.weight for n in self.nodes},
        }
        path.write_text(json.dumps(payload, indent=2) + "\n",
                        encoding="utf-8")
        return path

    # ---- selection helpers ----
    def select(self, token: str) -> list[AgentNode]:
        """Resolve a token to nodes: exact key, a runtime, a role, or all."""
        token = token.strip().lower()
        if token in ("all", "*"):
            return list(self.nodes)
        exact = [n for n in self.nodes if n.key == token]
        if exact:
            return exact
        by_runtime = [n for n in self.nodes if n.runtime == token]
        if by_runtime:
            return by_runtime
        by_role = [n for n in self.nodes if n.role == token]
        if by_role:
            return by_role
        raise KeyError(f"no fleet node, runtime, or role matches {token!r}")

    def set_enabled(self, token: str, enabled: bool) -> list[AgentNode]:
        nodes = self.select(token)
        for n in nodes:
            n.enabled = enabled
        return nodes

    def set_weight(self, token: str, weight: int) -> list[AgentNode]:
        if weight < 0:
            raise ValueError("weight must be >= 0")
        nodes = self.select(token)
        for n in nodes:
            n.weight = weight
        return nodes

    # ---- allocation ----
    def active_nodes(self) -> list[AgentNode]:
        return [n for n in self.nodes if n.enabled and n.weight > 0]

    def allocate(self, total: int) -> dict[str, int]:
        """Largest-remainder split of `total` threads across active nodes,
        proportional to weight. Inactive nodes map to 0."""
        alloc = {n.key: 0 for n in self.nodes}
        active = self.active_nodes()
        wsum = sum(n.weight for n in active)
        if total <= 0 or wsum == 0:
            return alloc
        raw = [(n, total * n.weight / wsum) for n in active]
        base = {n.key: int(math.floor(r)) for n, r in raw}
        used = sum(base.values())
        remainder = total - used
        # hand out the remainder to the largest fractional parts
        frac = sorted(raw, key=lambda nr: (nr[1] - math.floor(nr[1])),
                      reverse=True)
        for i in range(remainder):
            base[frac[i % len(frac)][0].key] += 1
        alloc.update(base)
        return alloc

    def thread_map(self, total: int) -> list[str | None]:
        """A list of length `total`; each cell holds the owning node key
        (contiguous blocks in node order) or None."""
        alloc = self.allocate(total)
        cells: list[str | None] = []
        for n in self.nodes:
            cells.extend([n.key] * alloc[n.key])
        cells += [None] * (total - len(cells))
        return cells[:total]


# ---- live utilization (deterministic given tick, so it is testable) ----

def load_for(key: str, tick: int) -> float:
    """Synthetic per-node utilization in [0, 1]. Smooth, phase-shifted per
    node so the dashboard looks alive without real process sampling."""
    phase = (sum(ord(c) for c in key) % 100) / 100 * math.tau
    base = 0.5 + 0.45 * math.sin(tick / 3.0 + phase)
    jitter = 0.05 * math.sin(tick / 1.3 + phase * 2)
    return max(0.0, min(1.0, base + jitter))


# ---- snapshot (JSON for web/desktop) ----

def resolve_total(root: str | Path, threads: str | None = None) -> int:
    if threads:
        return resolve_workers(threads)
    lvl = saved_level(root)
    if lvl:
        return resolve_workers(lvl)
    return logical_threads()


def snapshot(fleet: Fleet, root: str | Path, threads: str | None = None,
             tick: int = 0) -> dict:
    total = resolve_total(root, threads)
    alloc = fleet.allocate(total)
    nodes = []
    for n in fleet.nodes:
        a = alloc[n.key]
        util = load_for(n.key, tick) if (n.enabled and a) else 0.0
        nodes.append({
            "key": n.key, "runtime": n.runtime, "role": n.role,
            "label": n.label, "enabled": n.enabled, "weight": n.weight,
            "threads": a, "active_threads": round(a * util),
            "utilization": round(util, 3),
        })
    return {
        "logical_threads": logical_threads(),
        "budget_threads": total,
        "enabled_nodes": len(fleet.active_nodes()),
        "allocated_threads": sum(alloc.values()),
        "nodes": nodes,
    }


# ---- ANSI rendering ----

def _c(text: str, color: int, color_on: bool) -> str:
    if not color_on:
        return text
    return f"\x1b[38;5;{color}m{text}\x1b[0m"


def _bar(frac: float, width: int, color: int, color_on: bool) -> str:
    filled = round(frac * width)
    body = _FULL * filled + _HALF * (width - filled)
    return _c(body, color, color_on)


def render(fleet: Fleet, root: str | Path, threads: str | None = None,
           tick: int = 0, color: bool = True, width: int = 76) -> str:
    snap = snapshot(fleet, root, threads, tick)
    total = snap["budget_threads"]
    lines: list[str] = []

    title = "SURFING AI · AGENT FLEET"
    lines.append(_c(title, 250, color))
    lines.append(
        f"logical threads {snap['logical_threads']}   "
        f"budget {total}   allocated {snap['allocated_threads']}   "
        f"agents on {snap['enabled_nodes']}/{len(fleet.nodes)}")
    lines.append("")

    # thread map: one cell per budget thread, colored by owner, bright if
    # currently active
    cells = fleet.thread_map(total)
    util_by_key = {n["key"]: n["utilization"] for n in snap["nodes"]}
    active_left = {n["key"]: n["active_threads"] for n in snap["nodes"]}
    rendered = []
    for key in cells:
        if key is None:
            rendered.append(_c(_DOT, 240, color))
            continue
        node = next(n for n in fleet.nodes if n.key == key)
        if active_left.get(key, 0) > 0:
            active_left[key] -= 1
            rendered.append(_c(_FULL, node.color, color))
        else:
            rendered.append(_c(_HALF, node.color, color))
    lines.append("thread map  [" + "".join(rendered) + "]")
    lines.append("            █ active   ▒ held   · free")
    lines.append("")

    # per-node rows grouped by runtime
    last_runtime = None
    for n in fleet.nodes:
        info = next(x for x in snap["nodes"] if x["key"] == n.key)
        if n.runtime != last_runtime:
            spec = RUNTIMES[n.runtime]
            lines.append(_c(f"{spec.label}", n.color, color))
            last_runtime = n.runtime
        sw = _c("on ", 82, color) if n.enabled else _c("off", 240, color)
        glyph = _c(n.glyph, n.color, color)
        util = util_by_key[n.key]
        bar = _bar(util if n.enabled and info["threads"] else 0.0,
                   16, n.color, color)
        lines.append(
            f"  [{sw}] {glyph} {n.role:<11} "
            f"w{n.weight}  thr {info['threads']:>2} "
            f"{bar} {int(util * 100) if n.enabled and info['threads'] else 0:>3}%")
    return "\n".join(lines)


def render_watch(fleet: Fleet, root: str | Path, threads: str | None = None,
                 interval: float = 0.6, cycles: int | None = None,
                 color: bool = True) -> None:
    """Live loop: redraw the dashboard, animating dynamic thread control.
    `cycles=None` runs until interrupted; an integer makes it headless."""
    tick = 0
    try:
        while cycles is None or tick < cycles:
            frame = render(fleet, root, threads, tick=tick, color=color)
            print("\x1b[2J\x1b[H" + frame, flush=True)
            tick += 1
            if cycles is not None and tick >= cycles:
                break
            time.sleep(max(0.0, interval))
    except KeyboardInterrupt:
        pass
