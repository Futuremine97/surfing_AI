"""Tests for the user-controllable thread budget."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import thread_budget as tb


def test_levels_are_the_documented_set():
    assert tb.LEVELS == (20, 50, 60, 70, 80, 90, 100)


def test_added_levels_on_8_threads():
    assert tb.workers_for_percent(60, total=8) == 5   # 4.8 -> 5
    assert tb.workers_for_percent(80, total=8) == 6   # 6.4 -> 6
    assert tb.workers_for_percent(90, total=8) == 7   # 7.2 -> 7


def test_workers_for_percent_on_8_threads():
    assert tb.workers_for_percent(20, total=8) == 2   # 1.6 -> 2
    assert tb.workers_for_percent(50, total=8) == 4
    assert tb.workers_for_percent(70, total=8) == 6   # 5.6 -> 6
    assert tb.workers_for_percent(100, total=8) == 8


def test_workers_never_below_one():
    # 20% of 1 thread rounds to 0 -> clamped to 1
    assert tb.workers_for_percent(20, total=1) == 1
    assert tb.workers_for_percent(20, total=2) == 1   # 0.4 -> 0 -> 1


def test_workers_never_exceed_total():
    assert tb.workers_for_percent(100, total=4) == 4
    assert tb.workers_for_percent(70, total=2) == 1   # 1.4 -> 1


def test_normalize_level_variants():
    assert tb.normalize_level("50") == 50
    assert tb.normalize_level("50%") == 50
    assert tb.normalize_level(70) == 70
    assert tb.normalize_level("max") == 100
    assert tb.normalize_level("FULL") == 100
    assert tb.normalize_level("all") == 100


def test_normalize_level_rejects_bad_input():
    for bad in ("abc", "0", "120", "-5"):
        try:
            tb.normalize_level(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_resolve_workers_end_to_end():
    assert tb.resolve_workers("max", total=12) == 12
    assert tb.resolve_workers("50", total=12) == 6


def test_describe_shape():
    snap = tb.describe(total=8)
    assert snap["logical_threads"] == 8
    assert snap["default_level"] == 50
    assert [row["percent"] for row in snap["levels"]] == [20, 50, 60, 70, 80, 90, 100]
    assert [row["workers"] for row in snap["levels"]] == [2, 4, 5, 6, 6, 7, 8]


def test_logical_threads_matches_os():
    assert tb.logical_threads() == (os.cpu_count() or 2)
