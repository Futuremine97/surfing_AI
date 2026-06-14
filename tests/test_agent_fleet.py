"""Tests for the controllable agent fleet (graphical view model)."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.agent_fleet import Fleet, load_for, snapshot


def test_default_fleet_shape():
    f = Fleet.default()
    # 3 runtimes x (coordinator + explorer + builder + verifier)
    assert len(f.nodes) == 12
    assert {n.runtime for n in f.nodes} == {"antigravity", "codex", "claude"}
    assert {n.role for n in f.nodes} == {
        "coordinator", "explorer", "builder", "verifier"}


def test_allocation_sums_to_total():
    f = Fleet.default()
    for total in (0, 1, 4, 8, 13, 64):
        alloc = f.allocate(total)
        assert sum(alloc.values()) == total


def test_disabled_and_zero_weight_excluded():
    f = Fleet.default()
    f.set_enabled("codex", False)            # whole runtime off
    f.set_weight("claude-explorer", 0)        # one node muted
    alloc = f.allocate(20)
    assert all(alloc[n.key] == 0 for n in f.nodes if n.runtime == "codex")
    assert alloc["claude-explorer"] == 0
    assert sum(alloc.values()) == 20


def test_builder_outweighs_coordinator():
    f = Fleet.default()
    f.set_enabled("all", False)
    f.set_enabled("claude", True)             # only the claude lane
    alloc = f.allocate(24)
    assert alloc["claude-builder"] > alloc["claude-coordinator"]


def test_thread_map_matches_allocation():
    f = Fleet.default()
    total = 16
    alloc = f.allocate(total)
    cells = f.thread_map(total)
    assert len(cells) == total
    for n in f.nodes:
        assert cells.count(n.key) == alloc[n.key]


def test_select_resolution_and_errors():
    f = Fleet.default()
    assert len(f.select("claude")) == 4          # runtime
    assert len(f.select("builder")) == 3         # role across runtimes
    assert len(f.select("claude-builder")) == 1  # exact key
    assert len(f.select("all")) == 12
    try:
        f.select("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_load_for_is_bounded_and_deterministic():
    for key in ("claude-builder", "codex-explorer"):
        for tick in range(0, 50):
            v = load_for(key, tick)
            assert 0.0 <= v <= 1.0
        assert load_for(key, 7) == load_for(key, 7)


def test_persistence_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        f = Fleet.load(d)
        f.set_enabled("antigravity", False)
        f.set_weight("claude-verifier", 5)
        f.save(d)
        g = Fleet.load(d)
        assert all(not n.enabled for n in g.nodes
                   if n.runtime == "antigravity")
        assert next(n for n in g.nodes
                    if n.key == "claude-verifier").weight == 5


def test_snapshot_shape():
    with tempfile.TemporaryDirectory() as d:
        f = Fleet.default()
        snap = snapshot(f, d, threads="50", tick=0)
        assert snap["budget_threads"] >= 1
        assert len(snap["nodes"]) == 12
        assert snap["allocated_threads"] == snap["budget_threads"]
        for node in snap["nodes"]:
            assert 0 <= node["active_threads"] <= node["threads"] or \
                node["threads"] == 0
