#!/usr/bin/env node
/* surfing-ai — zero-dependency npm CLI for the Surfing AI private
 * harness.
 *
 *   npm install -g surfing-ai          (or: npm i -g github:Futuremine97/surfing_AI)
 *   surfing-ai                         multi-tab TUI (default)
 *
 * Concurrency model:
 *   multi-tab      each TUI tab is an independent private session
 *   multi-process  every tab spawns its own python3 REPL process
 *   multi-thread   :par a ; b ; c fans commands across CPU-count
 *                  PrivateTerminal workers (python threads) via
 *                  `surfing_ai max-procs --run`
 *
 * The Node layer adds no authority: every line still goes through the
 * Python harness (allowlist, file guard, redaction, audit).
 */

"use strict";

const { spawn, spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const ROOT = path.resolve(__dirname, "..");
const SCRIPT = path.join(ROOT, "scripts", "surfing_ai");
const PY = process.platform === "win32" ? "python" : "python3";
const VERSION = require(path.join(ROOT, "package.json")).version;

const PASSTHROUGH = new Set([
  "terminal-private", "tmux-private", "approvals", "backend-health",
  "desktop", "max-procs", "threads",
]);

function checkPython() {
  const probe = spawnSync(PY, ["--version"], { encoding: "utf8" });
  if (probe.error || probe.status !== 0) {
    console.error(`surfing-ai: ${PY} not found on PATH — install ` +
      "Python 3 first (https://www.python.org/downloads/)");
    process.exit(1);
  }
}

function usage() {
  console.log(`surfing-ai v${VERSION} — private agent harness CLI

usage:
  surfing-ai                       multi-tab TUI (default when a TTY)
  surfing-ai exec "<cmd>"          one-shot command through a private session
  surfing-ai par [--threads N] ... parallel commands across CPU workers
  surfing-ai desktop [--open]      desktop bridge (browser UI)
  surfing-ai max-procs [...]       tmux grid / headless parallel runner
  surfing-ai max-procs --threads N worker budget = N% of logical threads
                                   (N = 20 | 50 | 70 | 100 | max)
  surfing-ai threads               show threads + 20/50/70/100% budget
  surfing-ai terminal-private      plain single REPL
  surfing-ai backend-health        backend status (safe vocabulary)
  surfing-ai approvals list        approval queue
  surfing-ai --version | --help

TUI keys:
  Ctrl+T new tab   Ctrl+W close tab   Alt+1..9 / Alt+←/→ switch tab
  :par a ; b ; c   parallel run in current tab   Ctrl+C quit (all tabs)`);
}

/* ---------- non-interactive modes ---------- */

function passthrough(args) {
  const child = spawn(PY, [SCRIPT, ...args],
    { cwd: ROOT, stdio: "inherit" });
  child.on("exit", (code) => process.exit(code ?? 1));
}

function execOnce(command) {
  const child = spawn(PY, [SCRIPT, "terminal-private"], { cwd: ROOT });
  let out = "";
  child.stdout.on("data", (d) => { out += d.toString(); });
  child.stderr.on("data", (d) => { out += d.toString(); });
  child.stdin.write(command + "\n:quit\n");
  child.stdin.end();
  child.on("exit", (code) => {
    // strip the banner/prompt noise, keep result lines
    const lines = out.split("\n")
      .map((l) => l.replace(/private> /g, ""))
      .filter((l) =>
        !l.startsWith("surfing_ai terminal private mode") &&
        !l.startsWith("audit:") && !l.startsWith("summary written:"));
    process.stdout.write(lines.join("\n").trim() + "\n");
    process.exit(code ?? 1);
  });
}

/* ---------- TUI ---------- */

const ESC = "\x1b[";
const COLORS = {
  dim: `${ESC}90m`, accent: `${ESC}94m`, green: `${ESC}92m`,
  red: `${ESC}91m`, yellow: `${ESC}93m`, inverse: `${ESC}7m`,
  reset: `${ESC}0m`,
};
const MAX_BUFFER = 800;

class Tab {
  constructor(index, mode) {
    this.title = `tab ${index}`;
    this.mode = mode;
    this.buffer = [];
    this.proc = spawn(PY, [SCRIPT, "terminal-private", "--mode", mode],
      { cwd: ROOT });
    const push = (chunk) => {
      for (const line of chunk.toString().split("\n")) {
        if (line.trim() === "" && !this.buffer.length) continue;
        this.buffer.push(line.replace(/\r/g, ""));
      }
      if (this.buffer.length > MAX_BUFFER)
        this.buffer.splice(0, this.buffer.length - MAX_BUFFER);
    };
    this.proc.stdout.on("data", (d) => { push(d); tui.draw(); });
    this.proc.stderr.on("data", (d) => { push(d); tui.draw(); });
    this.proc.on("exit", () => {
      this.buffer.push(`${COLORS.dim}[session ended]${COLORS.reset}`);
      this.dead = true;
      tui.draw();
    });
  }

  send(line) {
    if (this.dead) return;
    if (line.startsWith(":par ")) {
      const commands = line.slice(5).split(";").map((s) => s.trim())
        .filter(Boolean);
      this.buffer.push(`${COLORS.yellow}par> ${commands.join("  |  ")}` +
        COLORS.reset);
      const runner = spawn(PY, [SCRIPT, "max-procs", "--run", ...commands],
        { cwd: ROOT });
      runner.stdout.on("data", (d) => {
        for (const l of d.toString().split("\n"))
          if (l.trim()) this.buffer.push(l);
        tui.draw();
      });
      runner.stderr.on("data", (d) => {
        for (const l of d.toString().split("\n"))
          if (l.trim()) this.buffer.push(COLORS.red + l + COLORS.reset);
        tui.draw();
      });
      return;
    }
    this.proc.stdin.write(line + "\n");
  }

  close() {
    if (!this.dead) {
      try { this.proc.stdin.write(":quit\n"); } catch (e) { /* gone */ }
      setTimeout(() => { try { this.proc.kill(); } catch (e) {} }, 500);
    }
  }
}

class Tui {
  constructor(mode) {
    this.mode = mode;
    this.tabs = [];
    this.active = 0;
    this.input = "";
    this.counter = 0;
  }

  start() {
    process.stdout.write(`${ESC}?1049h${ESC}?25l`); // alt screen
    process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.on("data", (d) => this.key(d));
    process.stdout.on("resize", () => this.draw());
    this.newTab();
  }

  stop() {
    for (const tab of this.tabs) tab.close();
    process.stdout.write(`${ESC}?1049l${ESC}?25h${COLORS.reset}`);
    setTimeout(() => process.exit(0), 600);
  }

  newTab() {
    this.counter += 1;
    this.tabs.push(new Tab(this.counter, this.mode));
    this.active = this.tabs.length - 1;
    this.draw();
  }

  closeTab() {
    if (!this.tabs.length) return;
    this.tabs[this.active].close();
    this.tabs.splice(this.active, 1);
    if (!this.tabs.length) return this.stop();
    this.active = Math.min(this.active, this.tabs.length - 1);
    this.draw();
  }

  key(data) {
    const s = data.toString("binary");
    if (s === "\x03") return this.stop();          // Ctrl+C
    if (s === "\x14") return this.newTab();        // Ctrl+T
    if (s === "\x17") return this.closeTab();      // Ctrl+W
    if (s === "\x1b[1;3D" || s === "\x1bb") {      // Alt+Left
      this.active = (this.active + this.tabs.length - 1) % this.tabs.length;
      return this.draw();
    }
    if (s === "\x1b[1;3C" || s === "\x1bf") {      // Alt+Right
      this.active = (this.active + 1) % this.tabs.length;
      return this.draw();
    }
    if (s.length === 2 && s[0] === "\x1b" && s[1] >= "1" && s[1] <= "9") {
      const want = s.charCodeAt(1) - 49;            // Alt+1..9
      if (want < this.tabs.length) { this.active = want; this.draw(); }
      return;
    }
    if (s === "\r") {                               // Enter
      const line = this.input;
      this.input = "";
      if (line.trim()) {
        const tab = this.tabs[this.active];
        tab.buffer.push(`${COLORS.accent}private> ${line}${COLORS.reset}`);
        tab.send(line);
      }
      return this.draw();
    }
    if (s === "\x7f" || s === "\b") {               // Backspace
      this.input = this.input.slice(0, -1);
      return this.draw();
    }
    if (s >= " " && s !== "\x7f" && !s.startsWith("\x1b")) {
      this.input += s;
      this.draw();
    }
  }

  draw() {
    if (!this.tabs.length) return;
    const rows = process.stdout.rows || 24;
    const cols = process.stdout.columns || 80;
    const tab = this.tabs[this.active];

    const bar = this.tabs.map((t, i) => {
      const label = ` ${i + 1}:${t.title}${t.dead ? "✕" : ""} `;
      return i === this.active
        ? COLORS.inverse + label + COLORS.reset
        : COLORS.dim + label + COLORS.reset;
    }).join("");
    const hint = `${COLORS.dim} ^T new ^W close Alt+n switch ` +
      `:par a;b parallel ^C quit${COLORS.reset}`;

    const bodyRows = rows - 3;
    const lines = tab.buffer.slice(-bodyRows);
    while (lines.length < bodyRows) lines.push("");

    const status = `${COLORS.dim}tabs:${this.tabs.length} ` +
      `procs:${this.tabs.filter((t) => !t.dead).length} ` +
      `mode:${this.mode}${COLORS.reset}`;

    let frame = `${ESC}H`;
    frame += (bar + hint).slice(0, cols * 3) + `${ESC}K\n`;
    for (const line of lines)
      frame += line.slice(0, cols + 40) + `${ESC}K\n`;
    frame += status + `${ESC}K\n`;
    frame += `${COLORS.green}private>${COLORS.reset} ` +
      this.input.slice(-(cols - 12)) + `${ESC}K`;
    process.stdout.write(frame);
  }
}

let tui = null;

/* ---------- entry ---------- */

function main() {
  const args = process.argv.slice(2);
  if (args[0] === "--version" || args[0] === "-v")
    return console.log(VERSION);
  if (args[0] === "--help" || args[0] === "-h" || args[0] === "help")
    return usage();

  if (!fs.existsSync(SCRIPT)) {
    console.error("surfing-ai: python harness missing from the package");
    process.exit(1);
  }
  checkPython();

  if (args[0] === "exec") {
    if (!args[1]) { console.error("usage: surfing-ai exec \"<cmd>\""); process.exit(1); }
    return execOnce(args.slice(1).join(" "));
  }
  if (args[0] === "par") {
    let rest = args.slice(1);
    // optional leading thread budget: par --threads 50 "a" "b"
    const pre = [];
    if (rest[0] === "--threads") {
      if (!rest[1]) { console.error("usage: surfing-ai par --threads <20|50|70|100|max> \"a\" \"b\""); process.exit(1); }
      pre.push("--threads", rest[1]);
      rest = rest.slice(2);
    }
    if (!rest.length) { console.error("usage: surfing-ai par [--threads N] \"a\" \"b\" ..."); process.exit(1); }
    return passthrough(["max-procs", ...pre, "--run", ...rest]);
  }
  if (PASSTHROUGH.has(args[0])) return passthrough(args);
  if (args.length) { usage(); process.exit(1); }

  if (!process.stdout.isTTY || !process.stdin.isTTY) {
    console.error("surfing-ai: no TTY — use `surfing-ai exec`, `par`, " +
      "or a subcommand (see --help)");
    process.exit(1);
  }
  const modeIdx = args.indexOf("--mode");
  const mode = modeIdx >= 0 ? args[modeIdx + 1] : "local-only";
  tui = new Tui(mode);
  tui.start();
}

main();
