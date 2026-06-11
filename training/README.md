# Nightly minGPT Training Pipeline

Trains a minGPT model automatically while you sleep, producing `.pth`
checkpoints that chain into the next post-training stage night after
night.

## How the chaining works

```
night 1: pretrain        scratch        -> mingpt_pretrain_run_*.pth
night 2: pretrain        resume latest  -> ...until target_steps reached
night N: post_train_1    resume latest  -> mingpt_post_train_1_run_*.pth
night M: post_train_2    resume latest  -> ...
```

State lives in `training/checkpoints/manifest.json`:

- every run records its parent checkpoint, steps done, final loss, status;
- `stage_progress` accumulates steps per stage; when a stage hits its
  `target_steps`, the next night automatically starts the next stage;
- `latest.pth` always points at the newest checkpoint, and the last 5
  checkpoints are kept (older ones rotate out).

A run stops at the step budget **or** the wall-clock deadline (default
06:30), whichever comes first — your machine is yours again by morning.
Interrupted runs are recorded and simply resumed the next night.

## Setup

```bash
pip install torch
git clone https://github.com/karpathy/minGPT training/minGPT
# put your plain-text corpus at training/data.txt (or set dataset_path)
bash training/install_schedule.sh     # 02:00 nightly, macOS launchd / cron
```

The launchd job wraps the run in `caffeinate -i` so the Mac does not
sleep mid-training, runs at low priority (`Nice 10`), and logs to
`training/logs/`.

## Verifying without torch

```bash
python3 training/nightly_train.py --dry-run
```

Dry runs exercise the full plan → run → checkpoint → manifest → next-stage
chain with placeholder checkpoints, so the scheduling logic is testable on
any machine (see `tests/test_training_pipeline.py`).

## Stages

Edit `DEFAULT_STAGES` in `training/pipeline.py` (or extend the manifest)
to change stage names and step targets. Checkpoints and logs stay out of
git; only the pipeline code is tracked.
