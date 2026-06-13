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

## Download (end users)

Tagged releases (`v*`) automatically build and attach installers to
[GitHub Releases](https://github.com/Futuremine97/surfing_AI/releases)
via `.github/workflows/release.yml` (`desktop` job):

| OS | artifact | notes |
|---|---|---|
| macOS | `.dmg` | universal (aarch64 + x86_64); unsigned — right-click → Open, or `xattr -cr` |
| Windows | `.exe` (NSIS), `.msi` | needs `python` on PATH |
| Linux | `.AppImage`, `.deb` | needs `python3` |

The bundle ships the Python harness inside the app resources
(`harness/`, `scripts/surfing_ai`, `desktop/ui/`). At launch the shell
resolves the code root in this order: `$SURFING_AI_ROOT` → bundle
resources → dev checkout. Installed apps run sessions in
`~/SurfingAI/` (created on first launch), which is where audit trails
land.

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
| GET | `/api/orchestrator` | – | cpu_count, max_processes, open/available |
| POST | `/api/orchestrator/max_sessions` | `{mode}` | fills up to max_processes sessions |
| GET | `/api/capabilities` | – | MCP/skill/plugin list + token-savings summary |
| POST | `/api/capabilities/toggle` | `{id, enabled}` | per-item enable/disable |

## Capability toggles and token savings

The `⛭ capabilities` pane (toolbar button or right-click → turn into
capabilities pane) lists every discovered MCP server (`.mcp.json`),
skill (`skills/`, `.agents/skills/`), and plugin (`.claude-plugin`,
`integrations/`) with an individual ON/OFF toggle
(`harness/capability_registry.py`, state in
`.surfing_ai_capabilities.json`, gitignored). MCP servers default to
OFF, matching the private-mode posture.

The pane and the status bar show estimated tokens saved per request
(and per 100 requests) from everything currently disabled. The
estimate is file-size arithmetic (`bytes / 4`) computed locally — by
construction, displaying it costs **zero** model tokens. The status
bar value is cached and refreshed at most every 30 s.

## Pane splitting (right-click) and max processes

Right-click any pane for the tmux/cmux-style menu: split right, split
down (each spawns a new private session), turn the pane into an
approvals or health pane, close the pane, or **⚡ fill max terminals**.
The `⚡ max procs` toolbar button (and menu item) asks the bridge for
`max_processes()` — CPU cores minus one, never below 1 — creates the
missing sessions, and re-tiles the grid into a near-square layout. The
status bar shows `procs open/max`.

The same maximum-process budget drives all three frontends
(`harness/process_orchestrator.py`):

```bash
# desktop app: ⚡ max procs button
python3 scripts/surfing_ai max-procs            # tmux tiled grid, one REPL per core
python3 scripts/surfing_ai max-procs --dry-run  # print the tmux commands
python3 scripts/surfing_ai max-procs --run "pytest -q" "python3 scripts/run_tests.py"
                                                # headless: parallel across N workers
```

Without tmux installed, `max-procs` prints `TMUX_NOT_FOUND` plus one
manual command per terminal window. Every parallel worker is a full
PrivateTerminal with its own tagged audit directory, so the allowlist,
file guard, redaction, and `files_sent_external = 0` invariants hold at
any parallelism.

## Menu-bar app (top-right status item)

Surfing AI lives in the macOS menu bar in two interchangeable forms;
both expose the same dropdown — **Open Surfing AI**, a **Thread Budget**
submenu (20/50/60/70/80/90/100%), **Backend Health**, **Approvals
Queue…**, and **Quit**.

1. **Tauri tray (native).** `desktop/src-tauri/src/main.rs` builds an
   `NSStatusItem` via `TrayIconBuilder` with a monochrome template wave
   glyph (`desktop/menubar/assets/menubar_template@2x.png`,
   `icon_as_template(true)` so macOS recolors it for light/dark bars).
   Selecting a thread level writes `~/SurfingAI/thread_budget.json`;
   Backend Health runs the harness and surfaces the summary in the tray
   tooltip. Needs the `tray-icon` + `image-png` Tauri features (already
   in `Cargo.toml`).

2. **Lite rumps app (dock-less).** `desktop/menubar/surfing_menubar.py`
   is a standalone `rumps` status-bar app with `LSUIElement = true` (no
   Dock icon, no app-switcher entry). It owns the same Python bridge.

   ```bash
   pip install rumps pyobjc
   python3 desktop/menubar/surfing_menubar.py        # run from a checkout
   python3 scripts/build_menubar_app.py --output dist # bundle "Surfing AI Menu Bar.app"
   python3 scripts/build_menubar_app.py --output dist --dmg
   ```

The chosen thread budget is honored by the harness: `surfing-ai
max-procs` with no `--threads`/`--panes` reads
`thread_budget.json` from its `--root` and sizes the worker pool from it
(`harness/thread_budget.saved_level`).

## App icon

The icon is a modern, flat California / San Diego sunset-surf mark
(sunset sky, low sun, turquoise→navy ocean swells with foam, a leaning
palm silhouette). It is generated reproducibly — no binary art to
hand-edit:

```bash
python3 scripts/make_icon.py
```

This renders `desktop/src-tauri/icons/` (`icon.png` 1024², the
16/32/64/128/256 PNGs, `icon.icns`, `icon.ico`), the menu-bar template
glyph under `desktop/menubar/assets/`, and refreshes `web/mark.svg` to
match. Both the Tauri bundle and the lite `.app` builders pick up
`icon.icns` automatically.
