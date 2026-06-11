# Verification-Gated Local Agent Harness

A verification-gated local agent harness for routing developer tasks across
small agents, coding agents, deterministic tools, reviewers, and human
approval gates.

This project focuses on token efficiency, safe local tool use, structured
verification, and rollback-aware execution.

All examples are synthetic. Private domain adapters, private research
artifacts, real experiment logs, and unpublished benchmarks are
intentionally excluded.

## How it works

```
User request
  -> context reduction      (raw context -> compact task state)
  -> reduction audit        (is the compact state enough to decide?)
  -> rule-based router      (small agent / coding agent / tool / human)
  -> executor + safe shell  (risk scan, timeout, cwd constraint, trace)
  -> verifier gate
  -> coupled approval gate  (high-risk actions only)
  -> trace store
  -> public release guard   (when publishing is requested)
```

Key properties:

- **Token efficiency.** Micro tasks (extract an error line, validate JSON,
  rank files, summarize a diff) never reach an expensive model; a
  deterministic small-agent layer handles them. Routing decisions are made
  from a compact task state, never from raw logs.
- **Reduction audit.** Before anything expensive runs, the harness checks
  that the compact state and the raw context lead to the same routing
  decision. If not, it gathers more targeted context cheaply and re-reduces.
- **Safe shell.** Destructive command patterns are refused outright; every
  command gets a risk scan, timeout, working-directory constraint, and a
  trace record.
- **Coupled approval for high-risk actions.** Deletion, visibility changes,
  publication, and marketplace submission proceed only when human intent
  matches the proposal, the verifier approves, a rollback checkpoint
  exists, and a worst-case simulation finds nothing catastrophic.
- **Public release guard.** Releases are blocked on secret findings,
  restricted-term findings, scrape-resilience failures (including git
  history), or missing user approval. Submission status is never claimed
  without evidence.

## Layout

```
harness/    core modules (state, reducer, router, gates, guards, trace)
tests/      test suite (synthetic fixtures only)
skills/verification_gated_agent_harness/   skill package
scripts/    test runner, demo, external validation
config/     validation config + example blocklist
```

## Quick start

```bash
python3 scripts/run_tests.py                       # run the test suite
python3 skills/verification_gated_agent_harness/scripts/run_skill_demo.py
python3 scripts/validate_skill_with_claude.py      # external review (optional)
```

No runtime dependencies; Python 3.10+. `pytest` and `pyyaml` are used when
present but not required.

## Release policy

`harness/public_release_guard.py` is the final gate. It must return
`PUBLIC_RELEASE_PASS` — and a human must approve — before anything in this
tree is published. The real blocklist lives in a gitignored file; only a
synthetic example ships in `config/`.
