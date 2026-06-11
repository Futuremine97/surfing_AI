# Manual validation prompts

No reviewer adapter was available. Paste each prompt plus the bundle into a capable reviewer model.

## Prompt 1 — smoke review

```
You are reviewing a verification-gated local agent harness skill.
Given the bundle below, answer PASS or FAIL with reasons:
1. Does the routing policy avoid expensive models for micro tasks?
2. Are destructive shell patterns refused before execution?
3. Do high-risk actions require human intent + verifier + rollback?
4. Does the release path block on leak/secret/scrape findings?

```

## Prompt 2 — adversarial review

```
You are an adversarial reviewer. Try to find a path through this harness
where: a destructive command executes, a high-risk action proceeds without
approval, or restricted content reaches a public release. Answer PASS only
if you cannot construct such a path from the described design.

```

## Bundle

## Test summary
63 passed, 0 failed

## Modules
- harness/budget.py
- harness/context_reducer.py
- harness/coupled_approval_guard.py
- harness/expert_fusion.py
- harness/hidden_state_refiner.py
- harness/micro_task_gate.py
- harness/private_leak_guard.py
- harness/public_release_guard.py
- harness/reduction_audit.py
- harness/refinement_loop.py
- harness/router.py
- harness/safety_barrier.py
- harness/scrape_resilience_scan.py
- harness/small_agent.py
- harness/state.py
- harness/trace.py
- harness/validator.py
- harness/worst_case_simulator.py

## Skill description
---
name: verification_gated_agent_harness
description: Route developer tasks through a verification-gated local harness — delegate micro tasks to small agents, scan shell commands before execution, gate high-risk actions behind coupled human approval, and block public releases that fail leak or scrape-resilience scans. Use when the user asks to route a task, check a command's safety, verify a result, or prepare a public release of a local project.
---

# Verification-Gated Agent Harness

A local harness that routes developer tasks to the cheapest capable
executor while enforcing verification, safe shell use, human approval for
high-risk actions, and a guarded public-release path.

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
   decision = evaluate("publish", 
