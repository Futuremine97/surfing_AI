import json
import subprocess
import sys
from pathlib import Path

from training.pipeline import CheckpointManager

STAGES = [
    {"name": "pretrain", "target_steps": 200},
    {"name": "post_train_1", "target_steps": 100},
]


def manager(tmp_path):
    return CheckpointManager(tmp_path / "ckpt", stages=STAGES, keep_last=3)


def run_night(m, steps):
    plan = m.plan_tonight()
    record = m.begin_run(plan)
    ckpt = m.checkpoint_path_for(record)
    ckpt.write_bytes(b"placeholder")
    m.complete_run(record, steps, 1.23, ckpt)
    return plan


def test_first_night_starts_from_scratch(tmp_path):
    m = manager(tmp_path)
    plan = m.plan_tonight()
    assert plan.stage == "pretrain"
    assert plan.resume_from is None
    assert plan.steps_remaining == 200


def test_second_night_resumes_from_latest(tmp_path):
    m = manager(tmp_path)
    run_night(m, steps=120)
    plan = m.plan_tonight()
    assert plan.stage == "pretrain"
    assert plan.resume_from is not None
    assert plan.steps_remaining == 80  # 200 - 120


def test_stage_advances_to_post_training(tmp_path):
    m = manager(tmp_path)
    run_night(m, steps=200)          # finishes pretrain
    plan = m.plan_tonight()
    assert plan.stage == "post_train_1"
    assert plan.resume_from is not None  # chains from pretrain checkpoint


def test_manifest_links_parent_checkpoints(tmp_path):
    m = manager(tmp_path)
    run_night(m, steps=200)
    run_night(m, steps=50)
    runs = m.load_manifest()["runs"]
    assert runs[0]["parent_checkpoint"] is None
    assert runs[1]["parent_checkpoint"] is not None
    assert runs[1]["stage"] == "post_train_1"
    assert runs[1]["status"] == "completed"


def test_checkpoint_rotation_keeps_last_n(tmp_path):
    m = manager(tmp_path)
    for _ in range(6):
        run_night(m, steps=10)
    pth = [p for p in (tmp_path / "ckpt").glob("*.pth")
           if p.name != "latest.pth"]
    assert len(pth) <= 3


def test_dry_run_cli_end_to_end(tmp_path):
    script = Path(__file__).resolve().parent.parent / "training" / "nightly_train.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--dry-run",
         "--checkpoint-dir", str(tmp_path / "ckpt"),
         "--dry-steps", "42"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads((tmp_path / "ckpt" / "manifest.json").read_text())
    assert manifest["stage_progress"]["pretrain"] == 42
    assert manifest["runs"][0]["status"] == "completed"
