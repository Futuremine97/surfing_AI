# Surfing AI Desktop (tmux/cmux-style)

A desktop workspace for terminal private mode: multiple sessions as
tabs (like cmux), each tab a multi-pane layout (like tmux) — terminal,
approvals, and backend health, with a live counters status bar.

## Architecture

```text
┌────────────────────────────────────────────────────────┐
│ Tauri shell (desktop/src-tauri, ~100 lines of Rust)    │
│   picks free port + random token                       │
│   spawns sidecar: python3 scripts/surfing_ai desktop   │
│   opens window at http://127.0.0.1:<port>/?token=...   │
└──────────────────────┬─────────────────────────────────┘
                       │ localhost HTTP + token
┌──────────────────────▼─────────────────────────────────┐
│ Python bridge (harness/desktop_bridge.py, stdlib only) │
│   serves desktop/ui/index.html                         │
│   JSON API: sessions / input / decision / state /      │
│             close / health                             │
│   SessionManager: one PrivateTerminal per tab          │
└──────────────────────┬─────────────────────────────────┘
                       │ direct calls (same process)
┌──────────────────────▼─────────────────────────────────┐
│ Terminal private mode (harness/terminal_private_mode)  │
│   modes, allowlist, file guard, redaction, approval    │
│   queue, audit log — single source of enforcement      │
└────────────────────────────────────────────────────────┘
```

The Tauri shell adds no authority: every invariant (allowlist, deny
paths, redaction, default-N approvals, `files_sent_external = 0`,
audit trail) is enforced in the Python layer, which is the same code
the plain REPL uses and is covered by the test suite.

## UI layout (per session tab)

```text
┌ tabs: [#1 local-only] [#2 redacted-external] [+ session] ┐
├───────────────────────────────┬──────────────────────────┤
│ terminal                      │ approvals                │
│  private> ls                  │  ┌ preview + approve /   │
│  private> git push …          │  │ deny buttons          │
│  BLOCKED: push publishes …    │  └ (default deny)        │
│                               ├──────────────────────────┤
│                               │ backend health           │
│  [input: private> _________]  │  claude: binary=present… │
├───────────────────────────────┴──────────────────────────┤
│ mode=… blocked=0 external_calls=0 files_sent_external=0  │
└───────────────────────────────────────────────────────────┘
```

## Approval flow over HTTP

The REPL's interactive `y/N` becomes two explicit steps:

1. `POST /api/sessions/<id>/input {"line": ":ask claude ..."}` →
   `{"status": "awaiting_approval", "preview": "..."}` — the redacted
   preview is rendered as a card with Approve / Deny buttons.
2. `POST /api/sessions/<id>/decision {"approve": true|false}` →
   the blocked ask thread resumes with `y` or `n`.

No decision within 300 s = deny. Nothing is transmitted before step 2
returns with `approve: true`, and file contents are never transmitted
in any case.

## Security model

- The bridge binds `127.0.0.1` only and rejects requests without the
  per-launch random token (`X-Bridge-Token` header or `?token=`).
- The UI is a single static file; no CDN, no external resources.
- The bridge itself never reads project files and never opens
  outbound connections.
- Each tab writes its own audit trail under
  `reports/surfing_ai_terminal_<ts>/`.

## Run

Browser mode (no toolchain needed):

```bash
python3 scripts/surfing_ai desktop --open
```

Native app (requires Rust + the Tauri CLI):

```bash
cargo install tauri-cli --version "^2"
cd desktop/src-tauri
cargo tauri dev          # development window
cargo tauri build        # .app / .dmg bundle
```

For an installed bundle, set `SURFING_AI_ROOT=/path/to/surfing_AI` so
the shell can find `scripts/surfing_ai`.

## API summary

| method | path | body | returns |
|---|---|---|---|
| GET | `/` | – | UI |
| GET | `/api/sessions` | – | session list |
| POST | `/api/sessions` | `{mode}` | new session state |
| GET | `/api/sessions/<id>/state` | – | mode, counters, output, pending |
| POST | `/api/sessions/<id>/input` | `{line}` | `done` \| `awaiting_approval` \| `busy` |
| POST | `/api/sessions/<id>/decision` | `{approve}` | ask result |
| POST | `/api/sessions/<id>/close` | – | finalizes audit summary |
| GET | `/api/health` | – | safe-vocabulary backend health |
