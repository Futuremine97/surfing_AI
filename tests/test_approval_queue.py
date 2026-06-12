import pytest

from harness.approval_queue import ApprovalQueue


def test_request_and_list(tmp_path):
    queue = ApprovalQueue(tmp_path / "q.jsonl")
    first = queue.request("external_prompt", "claude: hello")
    second = queue.request("file_read", "private/x.txt")
    assert first["id"] == 1 and second["id"] == 2
    assert [r["id"] for r in queue.list()] == [1, 2]
    assert len(queue.pending()) == 2


def test_approve_and_deny(tmp_path):
    queue = ApprovalQueue(tmp_path / "q.jsonl")
    queue.request("external_prompt", "a")
    queue.request("external_prompt", "b")
    approved = queue.approve(1)
    denied = queue.deny(2, "not needed")
    assert approved["status"] == "approved"
    assert denied["status"] == "denied" and denied["reason"] == "not needed"
    assert queue.pending() == []


def test_double_decision_rejected(tmp_path):
    queue = ApprovalQueue(tmp_path / "q.jsonl")
    queue.request("external_prompt", "a")
    queue.approve(1)
    with pytest.raises(ValueError, match="already approved"):
        queue.deny(1)


def test_unknown_id_raises(tmp_path):
    queue = ApprovalQueue(tmp_path / "q.jsonl")
    with pytest.raises(KeyError):
        queue.get(99)


def test_state_survives_reopen(tmp_path):
    path = tmp_path / "q.jsonl"
    ApprovalQueue(path).request("external_prompt", "persist me")
    reopened = ApprovalQueue(path)
    assert reopened.pending()[0]["label"] == "persist me"
    reopened.approve(1)
    assert ApprovalQueue(path).get(1)["status"] == "approved"
