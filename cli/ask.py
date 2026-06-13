#!/usr/bin/env python3
"""surfing-ai reverse-question driver.

Reads cli/reverse_questions.json, asks the entry question (cmux / tmux /
command) and the chosen command's tailored reverse-questions, maps each
answer to CLI flags via the option's `maps_to`, and assembles the final
`surfing-ai ...` command from `command_template`.

Two ways to drive it:

  interactive   python3 cli/ask.py
  scripted      resolve(spec, command_key, answers)  -> command string
                (used by the experiment harness and any automation)

`answers` shape (scripted):
  { question_id: {"value": <option value>, "inputs": {<name>: <text>}} }
`inputs` is only needed when the chosen option has `requires_input`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parent / "reverse_questions.json"
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
BRACKET = re.compile(r"\[([^\[\]]*)\]")


# ---------- spec loading / $ref ----------

def load_spec(path: Path = SPEC_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_ref(spec: dict, ref: str) -> dict:
    node = spec
    for part in ref.split("."):
        node = node[part]
    return node


def resolved_questions(spec: dict, command_key: str) -> list[dict]:
    out = []
    for q in spec["commands"][command_key]["questions"]:
        if "$ref" in q:
            resolved = dict(resolve_ref(spec, q["$ref"]))
            # merge sibling keys (e.g. ask_if) declared alongside the $ref
            for k, v in q.items():
                if k != "$ref":
                    resolved[k] = v
            out.append(resolved)
        else:
            out.append(q)
    return out


def find_option(question: dict, value):
    for opt in question["options"]:
        if opt["value"] == value:
            return opt
    raise KeyError(f"{question['id']}: no option with value {value!r}")


# ---------- answer -> slots ----------

def _norm_maps(maps_to):
    """maps_to may be a single {flag,value} or a list of them."""
    if maps_to is None:
        return []
    if isinstance(maps_to, list):
        return maps_to
    return [maps_to]


def _apply_mapping(m, question_id, inputs, named_slots, bare_flags):
    flag, value = m.get("flag"), m.get("value")

    # boolean bare flag, e.g. --dry-run / --open
    if value is True:
        if flag:
            bare_flags.add(flag)
        return

    if value is None:
        return  # informational option

    # value referencing an input placeholder, e.g. "{port}"
    mref = PLACEHOLDER.fullmatch(value) if isinstance(value, str) else None
    if mref:
        name = mref.group(1)
        if name not in inputs:
            raise ValueError(f"{question_id}: missing input '{name}'")
        named_slots[name] = inputs[name]
        return

    # literal value
    if flag:                                   # e.g. --mode local-only
        name = flag.lstrip("-").replace("-", "_")
        named_slots[name] = value
    else:                                       # positional, e.g. action=list
        named_slots[question_id] = value


def collect_slots(spec: dict, command_key: str, answers: dict):
    named_slots: dict[str, str] = {}
    bare_flags: set[str] = set()
    for q in resolved_questions(spec, command_key):
        # honor conditional questions
        cond = q.get("ask_if")
        if cond:
            ok = all(
                answers.get(dep, {}).get("value") in allowed
                for dep, allowed in cond.items()
            )
            if not ok:
                continue
        ans = answers.get(q["id"])
        if ans is None:
            continue
        opt = find_option(q, ans["value"])
        if opt.get("omit_when_default"):
            continue  # choosing the default means the flag is omitted
        inputs = ans.get("inputs", {})
        for m in _norm_maps(opt.get("maps_to")):
            _apply_mapping(m, q["id"], inputs, named_slots, bare_flags)
    return named_slots, bare_flags


# ---------- template rendering ----------

def render_template(template: str, named_slots: dict, bare_flags: set) -> str:
    def render_bracket(match):
        inner = match.group(1)
        names = PLACEHOLDER.findall(inner)
        if names:
            if all(n in named_slots for n in names):
                return PLACEHOLDER.sub(lambda m: named_slots[m.group(1)], inner)
            return ""  # an optional slot was not provided -> drop group
        # bare flag bracket, e.g. [--dry-run]
        flag = inner.strip()
        return inner if flag in bare_flags else ""

    rendered = BRACKET.sub(render_bracket, template)
    # required placeholders outside brackets
    rendered = PLACEHOLDER.sub(
        lambda m: named_slots.get(m.group(1), m.group(0)), rendered
    )
    return re.sub(r"\s+", " ", rendered).strip()


def resolve(spec: dict, command_key: str, answers: dict) -> str:
    named_slots, bare_flags = collect_slots(spec, command_key, answers)
    template = spec["commands"][command_key]["command_template"]
    return render_template(template, named_slots, bare_flags)


# ---------- interactive mode ----------

def _ask_choice(question: dict) -> dict:
    print("\n" + question["question"])
    opts = question["options"]
    for i, opt in enumerate(opts, 1):
        print(f"  {i}) {opt['label']} — {opt['description']}")
    while True:
        raw = input("선택 번호> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(opts):
            opt = opts[int(raw) - 1]
            break
        print("  유효한 번호를 입력하세요.")
    inputs = {}
    req = opt.get("requires_input")
    for name in ([req] if isinstance(req, str) else (req or [])):
        inputs[name] = input(f"  '{name}' 값 입력> ").strip()
    return {"value": opt["value"], "inputs": inputs}


def interactive(spec: dict) -> str:
    entry = spec["entry_question"]
    print(entry["question"])
    for i, opt in enumerate(entry["options"], 1):
        print(f"  {i}) {opt['label']} — {opt['description']}")
    routes = []
    while not routes:
        raw = input("트랙 선택> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(entry["options"]):
            routes = entry["options"][int(raw) - 1]["routes_to"]
    print("\n사용 가능한 커맨드:", ", ".join(routes))
    cmd = ""
    while cmd not in routes:
        cmd = input("커맨드> ").strip()
    answers = {}
    for q in resolved_questions(spec, cmd):
        cond = q.get("ask_if")
        if cond and not all(
            answers.get(d, {}).get("value") in a for d, a in cond.items()
        ):
            continue
        answers[q["id"]] = _ask_choice(q)
    command = resolve(spec, cmd, answers)
    print("\n조립된 명령:\n  " + command)
    return command


if __name__ == "__main__":
    interactive(load_spec())
