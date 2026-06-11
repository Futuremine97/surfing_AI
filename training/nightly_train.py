#!/usr/bin/env python3
"""Nightly minGPT training orchestrator.

Designed to run unattended while the user sleeps:

  1. Read the manifest, pick the current stage, find the latest .pth.
  2. Resume training from that checkpoint (or from scratch on night one).
  3. Train until the step budget or the wall-clock deadline (default
     06:30) is reached, checkpointing every --save-every steps.
  4. Write a new .pth, update latest.pth, append to the manifest — so the
     next night automatically continues into the next post-training stage.

torch/minGPT are imported lazily: with --dry-run (or when torch is
missing) the orchestrator plans and records without training, so the
chaining logic stays verifiable on any machine.
"""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from training.pipeline import CheckpointManager, StagePlan  # noqa: E402

DEFAULT_DEADLINE = "06:30"
DEFAULT_SAVE_EVERY = 1000


def parse_deadline(value: str) -> float:
    """Next occurrence of HH:MM as an epoch timestamp."""
    hour, minute = (int(x) for x in value.split(":"))
    now = datetime.datetime.now()
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if deadline <= now:
        deadline += datetime.timedelta(days=1)
    return deadline.timestamp()


def train_real(plan: StagePlan, manager: CheckpointManager, record,
               deadline_ts: float, save_every: int, args) -> tuple[int, float | None, Path | None]:
    """Real training loop. Requires torch + a minGPT implementation."""
    try:
        import torch
    except ImportError:
        print("torch is not installed — run with --dry-run, or:")
        print("  pip install torch")
        print("  git clone https://github.com/karpathy/minGPT training/minGPT")
        return 0, None, None

    from training.model_adapter import build_model, build_dataloader

    device = "mps" if torch.backends.mps.is_available() else (
        "cuda" if torch.cuda.is_available() else "cpu")
    model, optimizer = build_model(device, resume_from=plan.resume_from,
                                   config_path=args.config)
    loader = build_dataloader(args.config)

    steps_done, loss_value = 0, None
    checkpoint_path = manager.checkpoint_path_for(record)
    model.train()
    data_iter = iter(loader)
    while steps_done < plan.steps_remaining and time.time() < deadline_ts:
        try:
            batch = next(data_iter)
        except StopIteration:
            data_iter = iter(loader)
            batch = next(data_iter)
        x, y = (t.to(device) for t in batch)
        _, loss = model(x, y)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        steps_done += 1
        loss_value = float(loss.item())
        if steps_done % save_every == 0:
            torch.save({"model": model.state_dict(),
                        "optimizer": optimizer.state_dict(),
                        "stage": plan.stage,
                        "steps_done": steps_done},
                       checkpoint_path)
            print(f"[{time.strftime('%H:%M:%S')}] step {steps_done} "
                  f"loss {loss_value:.4f} -> {checkpoint_path.name}")

    torch.save({"model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "stage": plan.stage,
                "steps_done": steps_done}, checkpoint_path)
    return steps_done, loss_value, checkpoint_path


def train_dry(plan: StagePlan, manager: CheckpointManager, record,
              steps: int) -> tuple[int, float | None, Path | None]:
    """Plan-only run: writes a placeholder checkpoint to exercise the
    chaining logic end to end without torch."""
    checkpoint_path = manager.checkpoint_path_for(record)
    checkpoint_path.write_bytes(b"DRY-RUN PLACEHOLDER (not a real model)\n")
    return steps, None, checkpoint_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir",
                        default=str(Path(__file__).parent / "checkpoints"))
    parser.add_argument("--config",
                        default=str(Path(__file__).parent / "config.yaml"))
    parser.add_argument("--deadline", default=DEFAULT_DEADLINE,
                        help="stop time HH:MM (default 06:30)")
    parser.add_argument("--save-every", type=int, default=DEFAULT_SAVE_EVERY)
    parser.add_argument("--dry-run", action="store_true",
                        help="plan + manifest only; no torch required")
    parser.add_argument("--dry-steps", type=int, default=100)
    args = parser.parse_args()

    manager = CheckpointManager(args.checkpoint_dir)
    plan = manager.plan_tonight()
    print(f"stage: {plan.stage} | steps remaining: {plan.steps_remaining}")
    print(f"resume from: {plan.resume_from or '(scratch)'}")
    for note in plan.notes:
        print("note:", note)

    record = manager.begin_run(plan)
    deadline_ts = parse_deadline(args.deadline)

    try:
        if args.dry_run:
            steps, loss, ckpt = train_dry(plan, manager, record, args.dry_steps)
        else:
            steps, loss, ckpt = train_real(plan, manager, record,
                                           deadline_ts, args.save_every, args)
        status = "completed" if steps else "failed"
        manager.complete_run(record, steps, loss, ckpt, status=status)
        print(f"run {record.run_id}: {status}, {steps} steps"
              + (f", loss {loss:.4f}" if loss is not None else ""))
        if ckpt:
            print(f"checkpoint: {ckpt}")
        return 0 if steps else 1
    except KeyboardInterrupt:
        manager.complete_run(record, 0, None, None, status="interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
