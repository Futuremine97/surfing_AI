---
name: surfing-team
description: Launches parallel research, implementation, and verification subagents while the parent coordinates the final result.
---

# Surfing AI Team

Use the parent agent as coordinator.

1. Define three custom subagents when useful:
   - `surfing-explorer`: read-only repository research.
   - `surfing-builder`: scoped writes and focused tests.
   - `surfing-verifier`: read-only review and evidence collection.
2. Invoke independent subagents asynchronously so they run in parallel.
3. Use an isolated worktree for a write-heavy subagent when file ownership
   would otherwise overlap.
4. Monitor active agents in the subagent panel or with `/agents` in the CLI.
5. Fuse results only after implementation and verification evidence agree.
6. Keep inherited permissions intact and surface approval requests to the user.
7. Require explicit approval for destructive or publishing actions.

Antigravity supports nested delegation, but keep this workflow to one parent
and one subagent level unless the task genuinely requires more.
