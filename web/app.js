const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

async function postJSON(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function setText(selector, value) {
  const element = qs(selector);
  if (element) element.textContent = value;
}

function humanize(value) {
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function statusClass(value) {
  const text = String(value).toLowerCase();
  if (text.includes("pass") || text.includes("low") || text.includes("approved")) return "good";
  if (text.includes("high") || text.includes("fail") || text.includes("block")) return "bad";
  return "warn";
}

function installCopyButtons() {
  qsa("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.copy);
      const original = button.textContent;
      button.textContent = "COPIED";
      setTimeout(() => { button.textContent = original; }, 1200);
    });
  });
}

function installConsoleNavigation() {
  const navItems = qsa("[data-panel-target]");
  if (!navItems.length) return;
  const activate = (name) => {
    navItems.forEach((item) => item.classList.toggle("active", item.dataset.panelTarget === name));
    qsa("[data-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  navItems.forEach((item) => item.addEventListener("click", () => activate(item.dataset.panelTarget)));
  document.addEventListener("keydown", (event) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    const target = navItems[Number(event.key) - 1];
    if (target) activate(target.dataset.panelTarget);
  });
}

async function checkEngine() {
  const status = qs("#engine-status");
  if (!status) return;
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error();
    const data = await response.json();
    status.textContent = `${data.runtimes.length} runtimes supported`;
  } catch {
    status.textContent = "Connection unavailable";
  }
}

function renderFleetWaves(waves) {
  const strip = qs("#wave-strip");
  strip.replaceChildren();
  waves.forEach((wave, index) => {
    const item = document.createElement("div");
    item.className = "wave-step";
    const number = document.createElement("span");
    number.textContent = String(wave.number).padStart(2, "0");
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = wave.name;
    const description = document.createElement("small");
    description.textContent = wave.description;
    copy.append(title, description);
    item.append(number, copy);
    strip.append(item);
    if (index < waves.length - 1) {
      const arrow = document.createElement("i");
      arrow.textContent = "→";
      strip.append(arrow);
    }
  });
}

function renderFleetLanes(lanes) {
  const container = qs("#fleet-lanes");
  container.replaceChildren();
  lanes.forEach((lane) => {
    const card = document.createElement("article");
    card.className = `fleet-lane-card glass-panel ${lane.runtime}`;
    card.style.setProperty("--runtime-accent", lane.accent);

    const header = document.createElement("header");
    const identity = document.createElement("div");
    const dot = document.createElement("i");
    const title = document.createElement("strong");
    title.textContent = lane.label;
    identity.append(dot, title);
    const status = document.createElement("span");
    status.textContent = lane.status.toUpperCase();
    header.append(identity, status);

    const parent = document.createElement("div");
    parent.className = "parent-agent";
    const parentLabel = document.createElement("small");
    parentLabel.textContent = "PARENT AGENT";
    const parentRole = document.createElement("strong");
    parentRole.textContent = lane.parent.role;
    const parentObjective = document.createElement("p");
    parentObjective.textContent = lane.parent.objective;
    parent.append(parentLabel, parentRole, parentObjective);

    const subagents = document.createElement("div");
    subagents.className = "subagent-list";
    lane.subagents.forEach((agent) => {
      const row = document.createElement("div");
      const marker = document.createElement("span");
      marker.textContent = agent.role.slice(0, 1).toUpperCase();
      const copy = document.createElement("div");
      const role = document.createElement("strong");
      role.textContent = humanize(agent.role);
      const access = document.createElement("small");
      access.textContent = `${agent.access} · wave ${agent.wave}`;
      copy.append(role, access);
      const state = document.createElement("b");
      state.textContent = agent.status.toUpperCase();
      row.append(marker, copy, state);
      subagents.append(row);
    });

    const footer = document.createElement("footer");
    const hint = document.createElement("code");
    hint.textContent = lane.launch_hint;
    const constraint = document.createElement("small");
    constraint.textContent = lane.constraint;
    footer.append(hint, constraint);
    card.append(header, parent, subagents, footer);
    container.append(card);
  });
}

function installFleetForm() {
  const form = qs("#fleet-form");
  if (!form) return;

  qsa(".runtime-option input", form).forEach((input) => {
    input.addEventListener("change", () => {
      const label = input.closest(".runtime-option");
      label.classList.toggle("disabled", !input.checked);
      qs("b", label).textContent = input.checked ? "ON" : "OFF";
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const providers = qsa(".runtime-option input:checked", form).map((input) => input.value);
    if (!providers.length) {
      alert("Select at least one runtime.");
      return;
    }
    const button = qs("#fleet-button");
    button.disabled = true;
    qs("#fleet-result").hidden = true;
    qs("#fleet-loading").hidden = false;
    try {
      const data = await postJSON("/api/orchestrate", {
        goal: qs("#fleet-goal").value,
        context: qs("#fleet-context").value,
        providers,
      });
      setText("#fleet-result-title", `${data.provider_count} runtime lanes ready`);
      setText("#fleet-result-summary", `${data.task_id} · ${data.context_hint}`);
      setText("#fleet-agent-count", `${data.agent_count} PARENTS`);
      setText("#fleet-subagent-count", `${data.subagent_count} SUBAGENTS`);
      renderFleetWaves(data.waves);
      renderFleetLanes(data.lanes);
      qs("#fleet-result").hidden = false;
      qs("#fleet-result").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      alert(error.message);
    } finally {
      button.disabled = false;
      qs("#fleet-loading").hidden = true;
    }
  });
}

const examples = {
  bugfix: {
    goal: "Fix the failing authentication test and verify the session refresh flow.",
    context: "$ pytest tests/\ntests/test_auth.py FAILED\nE   ValueError: session token expired\nsee app/auth.py",
    criteria: "Authentication tests pass\nSession refresh behavior is verified",
  },
  shell: {
    goal: "Run the test suite and summarize any failures.",
    context: "$ pytest tests/ -q\nUse the current project directory only.",
    criteria: "Command risk scan passes\nTest result is recorded",
  },
  release: {
    goal: "Prepare this project for a public marketplace release.",
    context: "Run secret, private leak, scrape-resilience, and git history checks.",
    criteria: "Release guard passes\nHuman approval is recorded",
  },
};

let currentAnalysis = null;

function installExamples() {
  qsa("[data-example]").forEach((button) => {
    button.addEventListener("click", () => {
      const example = examples[button.dataset.example];
      qs("#goal").value = example.goal;
      qs("#context").value = example.context;
      qs("#criteria").value = example.criteria;
    });
  });
}

function renderRoute(route) {
  const track = qs("#route-track");
  track.replaceChildren();
  route.forEach((stage, index) => {
    const node = document.createElement("div");
    node.className = "route-step";
    const number = document.createElement("span");
    number.textContent = String(index + 1).padStart(2, "0");
    const title = document.createElement("strong");
    title.textContent = humanize(stage);
    const state = document.createElement("small");
    state.textContent = index === 0 ? "READY" : "QUEUED";
    node.append(number, title, state);
    track.append(node);
  });
  setText("#route-count", `${route.length} STAGES`);
}

function addTaskDetail(list, label, value) {
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = label;
  dd.textContent = Array.isArray(value) ? (value.join(", ") || "None") : (value || "None");
  list.append(dt, dd);
}

function renderTrace(events) {
  const list = qs("#trace-list");
  list.replaceChildren();
  events.forEach((event, index) => {
    const row = document.createElement("div");
    row.className = "trace-row";
    const number = document.createElement("span");
    number.textContent = String(index + 1).padStart(2, "0");
    const stage = document.createElement("strong");
    stage.textContent = humanize(event.stage);
    const detail = document.createElement("p");
    const payload = Object.entries(event)
      .filter(([key]) => !["ts", "task_id", "stage"].includes(key))
      .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(" → ") : value}`)
      .join(" · ");
    detail.textContent = payload;
    row.append(number, stage, detail);
    list.append(row);
  });
}

function renderAnalysis(data) {
  currentAnalysis = data;
  const task = data.task;
  setText("#result-title", humanize(task.task_type) + " pipeline");
  setText("#result-summary-copy", task.compact_summary);
  setText("#result-risk", `${task.risk_level.toUpperCase()} RISK`);
  setText("#result-audit", `AUDIT ${data.audit.status}`);
  qs("#result-risk").className = `data-badge ${statusClass(task.risk_level)}`;
  qs("#result-audit").className = `data-badge ${statusClass(data.audit.status)}`;
  renderRoute(data.route);
  setText("#task-type", task.task_type.toUpperCase());
  const details = qs("#task-details");
  details.replaceChildren();
  addTaskDetail(details, "Task ID", task.task_id);
  addTaskDetail(details, "Current error", task.current_error);
  addTaskDetail(details, "Relevant files", task.relevant_files);
  addTaskDetail(details, "Unknowns", task.unknowns);
  addTaskDetail(details, "Human gate", task.needs_human_approval ? "Required" : "Not required");
  renderTrace(data.trace);
  qs("#analysis-result").hidden = false;
  qs("#analysis-result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function installAnalysisForm() {
  const form = qs("#analysis-form");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = qs(".analyze-button");
    button.disabled = true;
    qs("#analysis-result").hidden = true;
    qs("#analysis-loading").hidden = false;
    try {
      const data = await postJSON("/api/analyze", {
        goal: qs("#goal").value,
        context: qs("#context").value,
        success_criteria: qs("#criteria").value.split("\n").map((line) => line.trim()).filter(Boolean),
      });
      renderAnalysis(data);
    } catch (error) {
      alert(error.message);
    } finally {
      button.disabled = false;
      qs("#analysis-loading").hidden = true;
    }
  });

  qs("#verify-button").addEventListener("click", async () => {
    if (!currentAnalysis) return;
    const button = qs("#verify-button");
    button.disabled = true;
    try {
      const criteriaMet = qs("#criteria-met").checked ? currentAnalysis.task.success_criteria : [];
      const data = await postJSON("/api/verify", {
        task: currentAnalysis.task,
        outcome: {
          tests_passed: qs("#tests-passed").checked,
          criteria_met: criteriaMet,
          evidence: [],
          side_effects: [],
        },
      });
      setText("#verify-status", data.approved ? "APPROVED" : "REJECTED");
      setText("#verify-message", data.reasons.join(" · "));
      qs("#verify-status").style.color = data.approved ? "var(--lime)" : "var(--coral)";
      renderTrace(data.trace);
    } catch (error) {
      setText("#verify-message", error.message);
    } finally {
      button.disabled = false;
    }
  });
}

function installCommandGuard() {
  const form = qs("#command-form");
  if (!form) return;
  qsa("[data-command]").forEach((button) => {
    button.addEventListener("click", () => {
      qs("#command-input").value = button.dataset.command;
    });
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const data = await postJSON("/api/scan-command", { command: qs("#command-input").value });
      const blocked = data.blocked;
      setText("#risk-score", data.risk_score.toFixed(2));
      setText("#scan-label", blocked ? "EXECUTION BLOCKED" : "SCAN PASSED");
      setText("#scan-title", blocked ? "Unsafe command detected" : "No blocked patterns found");
      setText("#scan-description", blocked
        ? "This command cannot pass the harness safety barrier."
        : data.warnings.length ? "The command is not blocked, but it requires review." : "The command is eligible for constrained execution.");
      const ring = qs("#risk-ring");
      ring.style.setProperty("--risk", `${data.risk_score * 360}deg`);
      ring.style.setProperty("background", `conic-gradient(${blocked ? "var(--coral)" : "var(--lime)"} var(--risk), #252c28 0)`);
      qs("#scan-label").style.color = blocked ? "var(--coral)" : "var(--lime)";
      const findings = qs("#scan-findings");
      findings.replaceChildren();
      const items = [...data.reasons, ...data.warnings];
      (items.length ? items : ["No risk findings"]).forEach((text) => {
        const item = document.createElement("span");
        item.textContent = text;
        findings.append(item);
      });
      qs("#command-result").hidden = false;
    } catch (error) {
      alert(error.message);
    }
  });
}

function installApprovalGate() {
  const form = qs("#approval-form");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const actionType = qs("#action-type").value;
    try {
      const data = await postJSON("/api/approval", {
        action_type: actionType,
        rollback_ref: qs("#rollback-ref").value || null,
        ai_proposal: qs("#ai-proposal").value,
        human_intent: qs("#human-intent").value || null,
        verifier_approved: qs("#verifier-approved").checked,
        payload: {
          rollback_ref: qs("#rollback-ref").value || null,
          release_guard_passed: qs("#release-guard-passed").checked,
        },
      });
      setText("#approval-symbol", data.approved ? "✓" : "×");
      setText("#approval-status", humanize(data.status));
      setText("#approval-reasons", [...data.reasons, ...data.worst_case.scenarios].join(" · "));
      const symbol = qs("#approval-symbol");
      symbol.style.color = data.approved ? "var(--lime)" : "var(--coral)";
      symbol.style.borderColor = data.approved ? "rgba(185,255,102,.25)" : "rgba(255,120,103,.25)";
      qs("#approval-result").hidden = false;
    } catch (error) {
      alert(error.message);
    }
  });
}

function addFinding(container, marker, text) {
  const row = document.createElement("div");
  row.className = "finding-row";
  const icon = document.createElement("span");
  icon.textContent = marker;
  const copy = document.createElement("div");
  copy.textContent = text;
  row.append(icon, copy);
  container.append(row);
}

function installReleaseCheck() {
  const button = qs("#release-button");
  if (!button) return;
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "SCANNING...";
    try {
      const data = await postJSON("/api/release-scan", {
        user_approved: qs("#release-approved").checked,
      });
      setText("#release-icon", data.passed ? "✓" : "!");
      setText("#release-status", humanize(data.status));
      qs("#release-icon").style.color = data.passed ? "var(--lime)" : "var(--yellow)";
      const findings = qs("#release-findings");
      findings.replaceChildren();
      const rows = [
        ...data.secret_findings.map((item) => ["SECRET", item]),
        ...data.leak_findings.map((item) => ["LEAK", item]),
        ...data.scrape_findings.map((item) => ["SCAN", item]),
        ...data.notes.map((item) => ["NOTE", item]),
      ];
      if (!rows.length) rows.push(["OK", data.passed ? "All release checks passed." : "No scan findings; approval may still be required."]);
      rows.forEach(([marker, text]) => addFinding(findings, marker, text));
      qs("#release-result").hidden = false;
    } catch (error) {
      alert(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "RUN RELEASE CHECK ↗";
    }
  });
}

function installChat() {
  const form = qs("#chat-form");
  if (!form) return;
  const input = qs("#chat-input");
  const sendButton = qs("#chat-send");
  const messagesBox = qs("#chat-messages");
  const agentToggle = qs("#chat-agent-mode");
  const editsToggle = qs("#chat-allow-edits");
  const workDirInput = qs("#chat-work-dir");
  const history = [];

  agentToggle.addEventListener("change", () => {
    editsToggle.disabled = !agentToggle.checked;
    workDirInput.disabled = !agentToggle.checked;
    if (!agentToggle.checked) editsToggle.checked = false;
  });

  const append = (role, text, label) => {
    const article = document.createElement("article");
    article.className = `chat-message ${role}`;
    const small = document.createElement("small");
    small.textContent = label || (role === "user" ? "YOU" : "SURFING AI");
    const p = document.createElement("p");
    p.textContent = text;
    article.append(small, p);
    messagesBox.appendChild(article);
    messagesBox.scrollTop = messagesBox.scrollHeight;
    return article;
  };

  const send = async () => {
    const text = input.value.trim();
    if (!text || sendButton.disabled) return;
    input.value = "";
    append("user", text);
    history.push({ role: "user", content: text });
    sendButton.disabled = true;
    const pending = append("assistant", "…", "SURFING AI");
    const startedAt = Date.now();
    const ticker = setInterval(() => {
      const seconds = Math.round((Date.now() - startedAt) / 1000);
      pending.querySelector("p").textContent =
        `Thinking… ${seconds}s (local backends may take a couple of minutes)`;
    }, 1000);
    try {
      const workDir = workDirInput.value.trim();
      const data = await postJSON("/api/chat", {
        messages: history,
        agent_mode: agentToggle.checked,
        allow_edits: editsToggle.checked,
        work_dirs: workDir ? [workDir] : [],
      });
      clearInterval(ticker);
      pending.querySelector("p").textContent = data.reply;
      history.push({ role: "assistant", content: data.reply });
      const modeBadge = qs("#chat-mode-badge");
      modeBadge.textContent = `MODE: ${humanize(data.mode)}` +
        (data.model ? ` · ${data.model}` : "");
      modeBadge.className = `data-badge ${data.mode === "model" ? "good" : "warn"}`;
      const routeBadge = qs("#chat-route-badge");
      routeBadge.textContent =
        `${humanize(data.analysis.task_type)} · risk ${data.analysis.risk_level}`;
      routeBadge.className =
        `data-badge ${statusClass(data.analysis.risk_level)}`;
    } catch (error) {
      clearInterval(ticker);
      pending.querySelector("p").textContent = `Error: ${error.message}`;
      pending.classList.add("error");
      history.pop();
    } finally {
      sendButton.disabled = false;
      input.focus();
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  installCopyButtons();
  installConsoleNavigation();
  installChat();
  installExamples();
  installFleetForm();
  installAnalysisForm();
  installCommandGuard();
  installApprovalGate();
  installReleaseCheck();
  checkEngine();
});
