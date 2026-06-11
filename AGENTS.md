# Surfing AI Agent Guide

Surfing AI coordinates Antigravity, Codex, and Claude while keeping each
runtime inside its native permission model.

## Operating Pattern

1. Reduce the request to a clear goal, constraints, and success criteria.
2. Delegate independent discovery, implementation, and verification work in
   parallel when the runtime supports it.
3. Keep one parent agent responsible for coordination and final synthesis.
4. Require concrete evidence before reporting completion.
5. Ask for explicit human approval before destructive, publishing,
   marketplace, or visibility-changing actions.

## Shared Roles

- `surfing-explorer`: read-only repository mapping and risk discovery.
- `surfing-builder`: scoped implementation in the active workspace.
- `surfing-verifier`: independent review and test evidence.

Prefer the `$surfing-team` skill for multi-agent work. Do not let multiple
write-capable agents edit the same files concurrently. Split ownership by
module, or keep implementation with one builder while other agents stay
read-only.
