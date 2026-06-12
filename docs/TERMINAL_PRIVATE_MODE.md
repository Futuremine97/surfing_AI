# Terminal Private Mode

A REPL (and optional tmux workspace) for working on private material
with hard guarantees about what can leave the machine.

## Quick start

```bash
scripts/surfing_ai_terminal_private.sh            # local-only REPL
python3 scripts/surfing_ai terminal-private       # same
python3 scripts/surfing_ai tmux-private           # 4-pane tmux workspace
python3 scripts/surfing_ai backend-health         # safe-vocabulary health
python3 scripts/surfing_ai approvals list         # approval queue
```

If tmux is not installed, `tmux-private` prints `TMUX_NOT_FOUND` plus
the plain-terminal fallback command — it never fails hard.

## Modes (three)

| mode | shell commands | external backends / MCP |
|---|---|---|
| `local-only` (default) | allowlist only | refused outright |
| `redacted-external` | allowlist only | preview + explicit `y` (default N), redacted prompt only |
| `audit` | dry-run logged, nothing executes | refused outright |

Switch inside the REPL with `:mode <name>`.

## Security invariants

1. External backends and MCP are OFF by default. A call is possible
   only in `redacted-external`, only after a written preview and an
   explicit `y` approval (pressing Enter means **No**).
2. Raw file contents are never transmitted. The session counter
   `files_sent_external` must be `0`; the session summary prints
   `SURFING_AI_TERMINAL_PRIVATE_PASS = true/false` accordingly.
3. Command execution is allowlist-only. Destructive or publishing
   patterns (`rm -rf`, `git push`, `git add -A`, `scp`, `mkfs`, `sudo`,
   `curl | sh`, ...) come back as `BLOCKED` with a reason and an
   alternative.
4. The file access guard works regardless of `.gitignore` —
   gitignore is not a security boundary. Deny rules live in
   `.surfing_ai_private.yaml` (defaults cover `private/`, `secrets/`,
   `.env`, `*.pem`, `*.key`, model dumps, databases; see
   `config/example_private_mode.yaml`).
5. Every session writes an audit trail under
   `reports/surfing_ai_terminal_<timestamp>/`; secret values are
   redacted from every output and never logged.

## REPL commands

```
:mode [name]      show / switch mode
:read <path>      read a file locally (guard applies; content stays local)
:ask <backend> <prompt>
                  external prompt (redacted-external mode only)
:health           backend health — vocabulary restricted to
                  present / missing / ok / failed / not_configured
:approvals        pending approval requests
:help             help text and shell allowlist
:quit             finalize session, write summary.md
```

Anything not starting with `:` is treated as a shell command and must
pass the allowlist (`ls`, `cat`, `grep`, `git status/diff/log/show/branch`,
`python3`, `pytest`, ...). Shell metacharacters (pipes, redirection,
command substitution) are rejected.

## External prompt flow (`redacted-external` only)

1. The prompt is redacted (API keys, tokens, `key=value` secrets).
2. A preview is printed and saved to
   `external_prompt_previews/` — exactly what would be sent.
3. An approval request is appended to the JSONL queue.
4. You are asked `send to <backend>? [y/N]` — default is N.
5. Only on `y` is the backend caller invoked, with the redacted prompt
   and zero files.

## Audit output

```
reports/surfing_ai_terminal_<ts>/
  session.json              mode, start time
  commands.log              executed commands + return codes
  blocked_commands.log      BLOCKED commands + reasons
  tool_calls.jsonl          local tool / external backend calls
  approvals.jsonl           approval decisions
  approvals_queue.jsonl     the JSONL approval queue itself
  external_prompt_previews/ saved previews
  backend_health.json       last :health snapshot
  summary.md                counters + SURFING_AI_TERMINAL_PRIVATE_PASS
```

## Design notes

Pure additive feature: nothing in `harness/web_app.py`, `web/`,
`harness/router.py`, or the existing tests is modified.
`backend_doctor` is reused (wrapped by `harness/backend_health.py`)
and `safety_barrier` / `public_release_guard` are import-only
dependencies.
