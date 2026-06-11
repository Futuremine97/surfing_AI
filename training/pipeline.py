"""Checkpoint chaining for nightly training runs.

Pure-stdlib logic, fully testable without torch:
- where checkpoints (.pth) live and how they rotate,
- a manifest that records each run and links it to its parent checkpoint,
- stage progression (pretrain -> post-training stages) so tonight's run
  automatically continues from where last night's run stopped.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_NAME = "manifest.json"
LATEST_NAME = "latest.pth"
DEFAULT_KEEP = 5

DEFAULT_STAGES = [
    {"name": "pretrain", "target_steps": 50_000},
    {"name": "post_train_1", "target_steps": 20_000},
    {"name": "post_train_2", "target_steps": 20_000},
]


@dataclass
class RunRecord:
    run_id: str
    stage: str
    started_at: float
    finished_at: float | None = None
    steps_done: int = 0
    final_loss: float | None = None
    parent_checkpoint: str | None = None
    checkpoint: str | None = None
    status: str = "running"  # running | completed | interrupted | failed


@dataclass
class StagePlan:
    stage: str
    resume_from: str | None
    steps_remaining: int
    notes: list[str] = field(default_factory=list)


class CheckpointManager:
    def __init__(self, checkpoint_dir: str | Path,
                 stages: list[dict] | None = None,
                 keep_last: int = DEFAULT_KEEP):
        self.dir = Path(checkpoint_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stages = stages or DEFAULT_STAGES
        self.keep_last = keep_last
        self.manifest_path = self.dir / MANIFEST_NAME

    # ---- manifest ------------------------------------------------------

    def load_manifest(self) -> dict:
        if self.manifest_path.is_file():
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return {"runs": [], "stage_progress": {}}

    def _save_manifest(self, manifest: dict) -> None:
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8")

    # ---- planning --------------------------------------------------------

    def current_stage(self) -> dict:
        """First stage whose target_steps are not yet reached."""
        progress = self.load_manifest()["stage_progress"]
        for stage in self.stages:
            done = progress.get(stage["name"], 0)
            if done < stage["target_steps"]:
                return stage
        return self.stages[-1]

    def latest_checkpoint(self) -> Path | None:
        latest = self.dir / LATEST_NAME
        if latest.exists():
            return latest
        candidates = sorted(self.dir.glob("*.pth"),
                            key=lambda p: p.stat().st_mtime)
        return candidates[-1] if candidates else None

    def plan_tonight(self) -> StagePlan:
        """Decide what tonight's run should do: which stage, where to
        resume, and how many steps remain in the stage."""
        manifest = self.load_manifest()
        stage = self.current_stage()
        done = manifest["stage_progress"].get(stage["name"], 0)
        remaining = max(0, stage["target_steps"] - done)
        resume = self.latest_checkpoint()
        notes = []
        if resume is None:
            notes.append("no checkpoint found; starting from scratch")
        if remaining == 0:
            notes.append("all configured stages complete; running "
                         "maintenance steps on final stage")
            remaining = stage["target_steps"] // 10
        return StagePlan(stage=stage["name"],
                         resume_from=str(resume) if resume else None,
                         steps_remaining=remaining, notes=notes)

    # ---- recording -------------------------------------------------------

    def begin_run(self, plan: StagePlan) -> RunRecord:
        run_id = time.strftime("run_%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        record = RunRecord(run_id=run_id, stage=plan.stage,
                           started_at=time.time(),
                           parent_checkpoint=plan.resume_from)
        manifest = self.load_manifest()
        manifest["runs"].append(record.__dict__)
        self._save_manifest(manifest)
        return record

    def checkpoint_path_for(self, record: RunRecord) -> Path:
        return self.dir / f"mingpt_{record.stage}_{record.run_id}.pth"

    def complete_run(self, record: RunRecord, steps_done: int,
                     final_loss: float | None,
                     checkpoint_written: Path | None,
                     status: str = "completed") -> None:
        record.finished_at = time.time()
        record.steps_done = steps_done
        record.final_loss = final_loss
        record.status = status
        record.checkpoint = str(checkpoint_written) if checkpoint_written else None

        manifest = self.load_manifest()
        for entry in manifest["runs"]:
            if entry["run_id"] == record.run_id:
                entry.update(record.__dict__)
        progress = manifest["stage_progress"]
        progress[record.stage] = progress.get(record.stage, 0) + steps_done
        self._save_manifest(manifest)

        if checkpoint_written and checkpoint_written.exists():
            latest = self.dir / LATEST_NAME
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            try:
                latest.symlink_to(checkpoint_written.name)
            except OSError:  # filesystems without symlink support
                latest.write_bytes(checkpoint_written.read_bytes())
            self._rotate()

    def _rotate(self) -> None:
        checkpoints = sorted(
            (p for p in self.dir.glob("*.pth") if p.name != LATEST_NAME),
            key=lambda p: p.stat().st_mtime)
        for stale in checkpoints[:-self.keep_last]:
            stale.unlink()
