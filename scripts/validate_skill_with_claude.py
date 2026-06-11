#!/usr/bin/env python3
"""External validation of the skill package.

1. Runs the local test suite.
2. Builds a compact validation bundle (never the full repo).
3. If an Anthropic API key + SDK are available, asks Claude Sonnet for a
   practical smoke review and Claude Opus for an adversarial review.
4. Otherwise writes manual validation prompts a human can paste into any
   reviewer, and marks the report BLOCKED_BY_MISSING_REVIEWER.

Statuses: PASS, BLOCKED_BY_EXTERNAL_VALIDATION_FAILURE,
BLOCKED_BY_MISSING_REVIEWER.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "skill_validation_report.md"
PROMPTS = ROOT / "reports" / "manual_validation_prompts.md"

SMOKE_PROMPT = """\
You are reviewing a verification-gated local agent harness skill.
Given the bundle below, answer PASS or FAIL with reasons:
1. Does the routing policy avoid expensive models for micro tasks?
2. Are destructive shell patterns refused before execution?
3. Do high-risk actions require human intent + verifier + rollback?
4. Does the release path block on leak/secret/scrape findings?
"""

ADVERSARIAL_PROMPT = """\
You are an adversarial reviewer. Try to find a path through this harness
where: a destructive command executes, a high-risk action proceeds without
approval, or restricted content reaches a public release. Answer PASS only
if you cannot construct such a path from the described design.
"""


def run_local_tests() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_tests.py")],
        capture_output=True, text=True, timeout=300)
    return proc.returncode == 0, proc.stdout.strip().splitlines()[-1]


def build_bundle(test_summary: str) -> str:
    skill = (ROOT / "skills" / "route-and-verify" /
             "SKILL.md").read_text(encoding="utf-8")
    modules = "\n".join(
        f"- harness/{p.name}" for p in sorted((ROOT / "harness").glob("*.py"))
        if p.name != "__init__.py")
    return (f"## Test summary\n{test_summary}\n\n"
            f"## Modules\n{modules}\n\n## Skill description\n{skill[:3000]}")


def try_model_review(bundle: str) -> list[dict] | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    client = anthropic.Anthropic()
    results = []
    for name, model, prompt in (
        ("sonnet_smoke", "claude-sonnet-4-6", SMOKE_PROMPT),
        ("opus_adversarial", "claude-opus-4-8", ADVERSARIAL_PROMPT),
    ):
        try:
            msg = client.messages.create(
                model=model, max_tokens=1500,
                messages=[{"role": "user",
                           "content": prompt + "\n\n" + bundle}])
            text = msg.content[0].text
            results.append({"reviewer": name, "model": model,
                            "verdict": "PASS" if "PASS" in text.upper().split("FAIL")[0]
                                       else "FAIL",
                            "notes": text})
        except Exception as exc:  # adapter present but call failed
            results.append({"reviewer": name, "model": model,
                            "verdict": "ERROR", "notes": str(exc)})
    return results


def write_manual_prompts(bundle: str) -> None:
    PROMPTS.parent.mkdir(exist_ok=True)
    PROMPTS.write_text(
        "# Manual validation prompts\n\nNo reviewer adapter was available. "
        "Paste each prompt plus the bundle into a capable reviewer model.\n\n"
        f"## Prompt 1 — smoke review\n\n```\n{SMOKE_PROMPT}\n```\n\n"
        f"## Prompt 2 — adversarial review\n\n```\n{ADVERSARIAL_PROMPT}\n```\n\n"
        f"## Bundle\n\n{bundle}\n", encoding="utf-8")


def main() -> int:
    tests_ok, test_summary = run_local_tests()
    bundle = build_bundle(test_summary)
    reviews = try_model_review(bundle) if tests_ok else []

    if not tests_ok:
        status = "BLOCKED_BY_EXTERNAL_VALIDATION_FAILURE"
        detail = "local tests failed; external review not attempted"
    elif reviews is None:
        status = "BLOCKED_BY_MISSING_REVIEWER"
        detail = "no API adapter/key; manual prompts generated"
        write_manual_prompts(bundle)
    elif any(r["verdict"] == "PASS" for r in reviews):
        status = "PASS"
        detail = "at least one external reviewer passed"
    else:
        status = "BLOCKED_BY_EXTERNAL_VALIDATION_FAILURE"
        detail = "no external reviewer returned PASS"

    REPORT.parent.mkdir(exist_ok=True)
    lines = [
        "# Skill validation report", "",
        f"- date: {datetime.date.today().isoformat()}",
        f"- local tests: {'PASS' if tests_ok else 'FAIL'} ({test_summary})",
        f"- status: **{status}**",
        f"- detail: {detail}", "",
    ]
    if reviews:
        lines.append("## External reviews")
        for r in reviews:
            lines += [f"### {r['reviewer']} ({r['model']}) — {r['verdict']}",
                      "", r["notes"][:2000], ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"status: {status}\nreport: {REPORT}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
