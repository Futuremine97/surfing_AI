from harness.budget import BudgetExceeded, TokenBudget, estimate_tokens
from harness.context_reducer import reduce_context
from harness.reduction_audit import audit_reduction
from harness.router import choose_route

RAW = """\
$ pytest tests/
collected 3 items
tests/test_app.py FAILED
E   ModuleNotFoundError: No module named 'requests'
see app/client.py and app/config.yaml
"""


def test_reduction_extracts_error_files_commands():
    s = reduce_context(RAW, "fix the failing test")
    assert s.current_error and "FAILED" in s.current_error or "Error" in s.current_error
    assert "app/client.py" in s.relevant_files
    assert any("pytest" in c for c in s.relevant_commands)
    assert s.task_type == "bugfix" and s.needs_code_edit


def test_compact_state_is_smaller_than_raw():
    raw = RAW * 50
    s = reduce_context(raw, "fix the failing test")
    assert estimate_tokens(s.compact_summary) < estimate_tokens(raw) / 10


def test_audit_passes_when_reduction_is_sufficient():
    s = reduce_context(RAW, "fix the failing test")
    result = audit_reduction(RAW, s, choose_route)
    assert result.passed and result.status == "PASS"


def test_audit_fails_when_compact_state_lost_information():
    s = reduce_context(RAW, "fix the failing test")
    s.current_error = None        # simulate lossy reduction
    s.relevant_files = []
    result = audit_reduction(RAW, s, choose_route)
    assert not result.passed
    assert "current_error" in result.missing_fields
    assert any("expensive model" in g for g in result.guidance)


def test_budget_enforced():
    b = TokenBudget(limit=10)
    b.charge("reduce", "x" * 20)  # 5 tokens
    assert b.remaining == 5
    try:
        b.charge("plan", "y" * 100)
        assert False, "expected BudgetExceeded"
    except BudgetExceeded:
        pass
