"""Tests for harness.security_gauge — level transitions, locking,
needle clamping, persistence, and router/model helpers."""

import json
import pytest
from pathlib import Path

from harness.security_gauge import LEVEL_DEFS, GaugeState, SecurityGauge
from harness.router import choose_route, model_for_gauge
from harness.state import TaskState


# ── GaugeState unit tests ────────────────────────────────────────────────────


def test_gauge_state_defaults():
    s = GaugeState()
    assert s.level == 0
    assert s.needle == 0.0
    assert s.locked_levels == []


def test_gauge_state_clamp():
    s = GaugeState(level=99, needle=2.5).clamp()
    assert s.level == 4
    assert s.needle == 1.0

    s2 = GaugeState(level=-1, needle=-0.5).clamp()
    assert s2.level == 0
    assert s2.needle == 0.0


def test_gauge_state_to_dict_includes_definition():
    s = GaugeState(level=2)
    d = s.to_dict()
    assert d["level"] == 2
    assert d["definition"]["name"] == "CAUTIOUS"
    assert "allowed_models" in d["definition"]


# ── SecurityGauge tests ──────────────────────────────────────────────────────


def test_security_gauge_initial_state(tmp_path):
    g = SecurityGauge(tmp_path)
    listing = g.listing()
    assert listing["level"] == 0
    assert listing["current"]["name"] == "LOCKED"
    assert listing["external_allowed"] is False


def test_set_level_transitions(tmp_path):
    g = SecurityGauge(tmp_path)
    result = g.set_level(2, needle=0.5)
    assert result["level"] == 2
    assert abs(result["needle"] - 0.5) < 1e-6
    assert result["definition"]["name"] == "CAUTIOUS"


def test_set_level_persists(tmp_path):
    g = SecurityGauge(tmp_path)
    g.set_level(3, needle=0.7)
    # fresh instance reads from disk
    g2 = SecurityGauge(tmp_path)
    assert g2.get().level == 3
    assert abs(g2.get().needle - 0.7) < 1e-6


def test_set_needle_clamped(tmp_path):
    g = SecurityGauge(tmp_path)
    g.set_level(1)
    g.set_needle(1.5)
    assert abs(g.get().needle - 1.0) < 1e-6
    g.set_needle(-0.3)
    assert abs(g.get().needle - 0.0) < 1e-6


def test_lock_prevents_entry(tmp_path):
    g = SecurityGauge(tmp_path)
    g.lock_level(3)
    result = g.set_level(3)
    assert "error" in result
    assert g.get().level == 0   # unchanged


def test_lock_ceiling_blocks_higher(tmp_path):
    """A locked level blocks entry to any level above it."""
    g = SecurityGauge(tmp_path)
    g.lock_level(2)
    result = g.set_level(4)
    assert "error" in result
    assert g.get().level == 0


def test_lock_drops_active_level(tmp_path):
    """Locking the currently active level drops the gauge down."""
    g = SecurityGauge(tmp_path)
    g.set_level(3)
    g.lock_level(3)
    assert g.get().level < 3


def test_unlock_restores_access(tmp_path):
    g = SecurityGauge(tmp_path)
    g.lock_level(2)
    g.unlock_level(2)
    result = g.set_level(2)
    assert result["level"] == 2
    assert "error" not in result


def test_listing_shape(tmp_path):
    g = SecurityGauge(tmp_path)
    g.set_level(2)
    listing = g.listing()
    assert len(listing["levels"]) == 5
    assert listing["external_allowed"] is True
    assert listing["redact_required"] is True
    assert listing["approval_required"] is True


# ── model access matrix ──────────────────────────────────────────────────────


def test_level0_no_models_allowed(tmp_path):
    g = SecurityGauge(tmp_path)
    assert g.is_model_allowed("claude-haiku-4-5-20251001") is False
    assert g.is_model_allowed("gpt-4o") is False


def test_level2_allows_small_models(tmp_path):
    g = SecurityGauge(tmp_path)
    g.set_level(2)
    assert g.is_model_allowed("claude-haiku-4-5-20251001") is True
    assert g.is_model_allowed("gpt-4o") is False


def test_level4_allows_all_models(tmp_path):
    g = SecurityGauge(tmp_path)
    g.set_level(4)
    for model in ["claude-fable-5", "claude-opus-4-8", "gpt-4o", "o3"]:
        assert g.is_model_allowed(model) is True


def test_level0_external_blocked(tmp_path):
    g = SecurityGauge(tmp_path)
    assert g.is_external_allowed() is False


def test_level3_external_allowed(tmp_path):
    g = SecurityGauge(tmp_path)
    g.set_level(3)
    assert g.is_external_allowed() is True


# ── route filtering ──────────────────────────────────────────────────────────


def test_level0_route_filter(tmp_path):
    g = SecurityGauge(tmp_path)
    routes = ["context_reducer", "coding_agent", "test_runner", "verifier",
              "command_risk_scan", "shell_tool"]
    filtered = g.filter_routes(routes)
    assert set(filtered) <= {"command_risk_scan", "shell_tool"}


def test_level4_route_filter_passthrough(tmp_path):
    g = SecurityGauge(tmp_path)
    g.set_level(4)
    routes = ["context_reducer", "coding_agent", "human_approval"]
    assert g.filter_routes(routes) == routes


# ── router integration ───────────────────────────────────────────────────────


def _simple_task(**kwargs):
    defaults = dict(task_id="t1", user_goal="g", task_type="general",
                    risk_level="low", needs_code_edit=False, needs_shell=False,
                    needs_human_approval=False, public_release_requested=False)
    defaults.update(kwargs)
    return TaskState(**defaults)


def test_choose_route_respects_gauge_level0(tmp_path):
    """At level 0 only 'command_risk_scan' (the safe fallback) survives."""
    g = SecurityGauge(tmp_path)   # level 0
    task = _simple_task(needs_code_edit=True)
    route = choose_route(task, gauge=g)
    # all coding routes stripped; fallback applied
    assert "coding_agent" not in route


def test_choose_route_no_gauge_unchanged(tmp_path):
    """Without gauge arg the router behaves as before."""
    task = _simple_task(needs_code_edit=True)
    route = choose_route(task)
    assert "coding_agent" in route


def test_model_for_gauge_level0_returns_none(tmp_path):
    g = SecurityGauge(tmp_path)   # level 0 — no models
    assert model_for_gauge(g) is None


def test_model_for_gauge_level2_returns_small(tmp_path):
    g = SecurityGauge(tmp_path)
    g.set_level(2)
    model = model_for_gauge(g)
    assert model is not None
    assert model in LEVEL_DEFS[2]["allowed_models"]


def test_model_for_gauge_level4_returns_max(tmp_path):
    g = SecurityGauge(tmp_path)
    g.set_level(4)
    model = model_for_gauge(g)
    assert model in LEVEL_DEFS[4]["allowed_models"]


def test_model_for_gauge_none_arg():
    assert model_for_gauge(None) is None


# ── level definitions sanity ─────────────────────────────────────────────────


def test_level_defs_complete():
    assert len(LEVEL_DEFS) == 5
    for i, d in enumerate(LEVEL_DEFS):
        assert d["level"] == i
        assert d["name"]
        assert d["color"].startswith("#")
        assert isinstance(d["external_allowed"], bool)
