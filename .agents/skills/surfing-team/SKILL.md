---
name: surfing-team
description: Coordinates parallel explorer, builder, and verifier agents for a developer task. Use when work can be split across agents or needs independent verification.
---

# Surfing Team

Treat the user's request as the parent agent's goal.

1. State the goal, constraints, and measurable success criteria.
2. Start an explorer, builder, and verifier concurrently when their work is
   independent. Keep the explorer and verifier read-only.
3. Give the builder exclusive ownership of its files. Do not create competing
   write agents for the same module.
4. Continue useful parent-agent work while subagents run.
5. Collect each result and compare claims against test or inspection evidence.
6. Run the verification-gated route from `skills/route-and-verify/SKILL.md`
   before accepting the final result.
7. Stop for human approval before destructive, publish, marketplace, or
   visibility-changing actions.

For Antigravity, use asynchronous `invoke_subagent` calls and monitor them in
the subagent panel or `/agents`. For Codex, use the configured
`surfing-explorer`, `surfing-builder`, and `surfing-verifier` roles.
