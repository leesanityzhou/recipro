from __future__ import annotations

import json

from .models import ImprovementTask, TaskOutcome


def scan_prompt(*, max_improvements: int, max_files_per_change: int) -> str:
    example = {
        "tasks": [
            {
                "title": "Short improvement title",
                "description": "Why this matters and exactly what should change.",
                "files": ["path/to/file.py"],
                "expected_change": "One-sentence expected outcome.",
                "manual_actions": [],
            }
        ]
    }
    return f"""
You are the critic agent in Recipro, a dual-agent code-improvement loop.

Inspect the repository in the current working directory and return up to {max_improvements} safe, high-impact improvements that can be implemented in small pull requests.

Prioritize:
- bugs
- correctness gaps
- maintainability
- observability
- security hardening
- small performance wins

Hard constraints:
- no architecture rewrites
- no dependency upgrades
- no migrations
- no API changes
- no task that should touch more than {max_files_per_change} files
- prefer tasks that another agent can complete locally without outside systems

Return strict JSON only, matching this shape:
{json.dumps(example, ensure_ascii=False, indent=2)}
""".strip()


def implement_prompt(
    task: ImprovementTask,
    *,
    max_files_per_change: int,
    feedback: list[str],
) -> str:
    feedback_block = "\n".join(f"- {item}" for item in feedback) if feedback else "- None"
    files_block = "\n".join(f"- {item}" for item in task.files) if task.files else "- Unknown"
    return f"""
You are the builder agent in Recipro.

Implement the following safe improvement in the current repository.

Title:
{task.title}

Description:
{task.description}

Likely files:
{files_block}

Expected change:
{task.expected_change or "Not specified."}

Feedback to address this round:
{feedback_block}

Hard constraints:
- keep the patch minimal and safe
- modify at most {max_files_per_change} files
- do not change public APIs unless the task explicitly requires it
- do not upgrade dependencies
- do not run git commands
- if you run tests, keep them as small and relevant as possible

After editing the repository, return strict JSON only:
{{
  "summary": "short summary of the implementation",
  "changed_files": ["path/to/file.py"],
  "tests_ran": ["pytest tests/test_example.py"],
  "manual_actions": []
}}
""".strip()


def review_prompt() -> str:
    return """
You are the critic agent in Recipro.

Review the current repository changes against HEAD. Focus only on material issues:
- correctness bugs
- regressions
- unsafe behavior
- missing edge-case handling
- validation gaps

Ignore style-only nitpicks.

Return strict JSON only:
{
  "status": "pass" or "fail",
  "summary": "short explanation",
  "findings": ["concrete fix 1", "concrete fix 2"],
  "manual_actions": []
}

Use "pass" only when there are no material findings left to fix before commit.
""".strip()


def report_prompt(outcomes: list[TaskOutcome], repo_path: str, run_date: str) -> str:
    payload = [outcome.to_dict() for outcome in outcomes]
    return f"""
You are summarizing a Recipro run.

Repository:
{repo_path}

Date:
{run_date}

Task outcomes JSON:
{json.dumps(payload, ensure_ascii=False, indent=2)}

Return strict JSON only:
{{
  "improvements_completed": ["..."],
  "files_changed": ["..."],
  "risks": ["..."],
  "manual_actions_required": ["..."]
}}
""".strip()


def pr_body(outcome: TaskOutcome) -> str:
    lines = [
        "## Summary",
        outcome.summary or outcome.task.description,
        "",
        "## Task",
        f"- {outcome.task.title}",
    ]

    if outcome.changed_files:
        lines.extend(["", "## Files Changed"])
        lines.extend(f"- {path}" for path in outcome.changed_files)

    if outcome.tests_ran:
        lines.extend(["", "## Validation"])
        lines.extend(f"- {command}" for command in outcome.tests_ran)

    if outcome.manual_actions:
        lines.extend(["", "## Manual Actions Required"])
        lines.extend(f"- {item}" for item in outcome.manual_actions)

    return "\n".join(lines).strip()

