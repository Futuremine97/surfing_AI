---
name: Route and Verify
description: Route developer tasks through a verification-gated local harness — delegate micro tasks to small agents, scan shell commands before execution, gate high-risk actions behind coupled human approval, and block public releases that fail leak or scrape-resilience scans. Use when the user asks to route a task, check a command's safety, verify a result, or prepare a public release of a local project.
argument-hint: [task]
---

# Verification-Gated Agent Harness

A local harness that routes developer tasks to the cheapest capable
executor while enforcing verification, safe shell use, human approval for
high-risk actions, and a guarded public-release path.

Treat `$ARGUMENTS` as the user's task. The current Claude Code working
directory is the target project. The bundled implementation is available at
`${CLAUDE_PLUGIN_ROOT}`; do not edit files in the plugin cache.

## When to use

- Deciding whether a task needs a large model, a coding agent, a small
  deterministic agent, or just a tool.
- Checking a shell command for destructive patterns before running it.
- Verifying a task outcome against success criteria.
- Preparing a repository for public release (leak scan, secret scan,
  scrape-resilience scan, approval gate).

## Workflow

1. **Reduce context.** Build a compact task state from the raw request:

   ```python
   # Run with PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" when importing the bundle.
   from harness.context_reducer import reduce_context
   state = reduce_context(raw_text, user_goal)
   ```

2. **Audit the reduction.** Confirm the compact state preserves enough
   information for the next decision:

   ```python
   from harness.reduction_audit import audit_reduction
   from harness.router import choose_route
   result = audit_reduction(raw_text, state, choose_route)
   # On FAIL: gather targeted context cheaply, re-reduce. Do not call an
   # expensive model yet.
   ```

3. **Route.** `choose_route(state)` returns the stage pipeline. Micro tasks
   (extract / classify / summarize / validate) go to the small agent only —
   never to an expensive model.

4. **Delegate micro tasks.**

   ```python
   from harness.small_agent import SmallAgent
   from harness.micro_task_gate import guard_payload
   guard_payload(payload)            # rejects side effects / restricted text
   SmallAgent().run("extract_first_error_line", log_text)
   ```

   Small agents never write files, run shell commands, or touch the network.

5. **Run shell safely.**

   ```python
   from harness.safety_barrier import run_safe
   run_safe("pytest -q", cwd=project_dir, timeout=120, trace=trace)
   ```

   Destructive patterns are refused outright; every command is scanned,
   time-limited, cwd-constrained, and traced.

6. **Verify.** `VerifierGate().verify(state, outcome)` — code edits require
   passing tests; unmet success criteria reject the outcome.

7. **Gate high-risk actions.** Deletion, visibility changes, publication,
   and marketplace submission require the coupled approval state: human
   intent matching the proposal, verifier approval, a rollback checkpoint,
   and a clean worst-case simulation.

   ```python
   from harness.coupled_approval_guard import CoupledApprovalState, evaluate
   decision = evaluate("publish", payload, approval_state)
   ```

8. **Guard public releases.**

   ```python
   from harness.public_release_guard import run_release_check
   report = run_release_check(repo_root, user_approved=True)
   # PUBLIC_RELEASE_PASS or a specific BLOCKED_* status
   ```

## Hard rules

- Never send full raw logs to a large model when the compact state is enough.
- Never use an expensive model for tiny extraction/classification tasks.
- Never let small agents write files or run shell commands.
- Never run destructive commands without explicit human approval.
- Never claim a marketplace submission without submission evidence
  (`marketplace_status(evidence)` enforces this).
- All examples must stay synthetic; keep the real blocklist gitignored.

## Scripts

- `scripts/run_skill_demo.py` — end-to-end synthetic walkthrough.
- `scripts/run_tests.py` — dependency-free test runner.
- `scripts/validate_skill_with_claude.py` — external model validation
  (falls back to generating manual review prompts when no API key is set).
