# Surfing AI

Surfing AI coordinates Antigravity, Codex, and Claude agents in one local,
verification-gated workflow. A parent agent owns the mission, independent
explorer, builder, and verifier subagents run in parallel, and the final result
advances only with evidence.

## What ships

- **Three native runtimes.** Antigravity plugin and skill, Codex project
  multi-agent roles, and Claude Code plugin agents.
- **Parallel orchestration.** The local console creates concurrent runtime
  lanes with isolated explorer, builder, and verifier responsibilities.
- **Verification gates.** Tests and success criteria must agree before an
  implementation is accepted.
- **Local safety.** Commands are scanned before execution, high-risk actions
  require coupled human approval, and public releases pass leak and history
  checks.
- **Cross-platform download.** One ZIP includes launchers for macOS, Windows,
  and Linux with no runtime package dependencies.

All examples are synthetic. Private adapters, unpublished research artifacts,
real experiment logs, and private benchmarks are intentionally excluded.

## Run locally

```bash
python3 scripts/run_tests.py
python3 scripts/run_web.py --open
```

Open:

- `http://127.0.0.1:4173/` - Surfing AI website
- `http://127.0.0.1:4173/app` - interactive agent fleet console
- `http://127.0.0.1:4173/download/surfing-ai.zip` - downloadable package

The browser console plans native runtime work but never silently starts an
external agent CLI. Each runtime keeps its own sandbox, permissions, and
approval flow.

## Antigravity

Install the bundled plugin from the checkout or downloaded ZIP:

```bash
agy plugin install integrations/antigravity
```

Invoke `/surfing-team`. The parent can define and asynchronously invoke
explorer, builder, and verifier subagents. Active agents are visible in the
subagent panel or `/agents`.

The repository also includes a workspace skill at
`.agents/skills/surfing-team/SKILL.md`.

## Codex

Open this trusted repository in Codex:

```bash
codex
```

`.codex/config.toml` enables multi-agent mode and registers:

- `surfing-explorer`
- `surfing-builder`
- `surfing-verifier`

Use `$surfing-team` or ask Codex to delegate independent work in parallel.
`AGENTS.md` defines the shared evidence and ownership rules.

## Claude Code

Install from the repository marketplace:

```text
/plugin marketplace add Futuremine97/surfing_AI
/plugin install verification-gated-harness@futuremine97-tools
/reload-plugins
```

Equivalent terminal commands:

```bash
claude plugin marketplace add Futuremine97/surfing_AI
claude plugin install verification-gated-harness@futuremine97-tools
```

Run:

```text
/verification-gated-harness:route-and-verify fix the failing tests
```

The plugin includes `surfing-explorer`, `surfing-builder`, and
`surfing-verifier` agents. Claude subagents report to the parent; they do not
spawn additional subagents.

For local plugin development:

```bash
claude --plugin-dir .
```

## Download and release

Build the curated ZIP:

```bash
python3 scripts/build_release.py
```

The archive intentionally excludes private material, Git history, caches, and
editor metadata. Pushing a tag such as `v0.1.0` runs the release workflow,
tests the project, and attaches `surfing-ai.zip` plus its SHA-256 checksum.

## Architecture

```text
User mission
  -> compact task state + reduction audit
  -> Antigravity / Codex / Claude parent lanes
  -> parallel explorer / builder / verifier subagents
  -> verification-weighted evidence fusion
  -> human approval for high-risk actions
  -> trace + public release guard
```

Core modules live in `harness/`, runtime integrations in `.agents/`,
`.codex/`, `agents/`, and `integrations/`, and the website in `web/`.

## License

Licensed under the [Apache License 2.0](LICENSE). Commercial use,
modification, distribution, and private use are permitted under its terms.
