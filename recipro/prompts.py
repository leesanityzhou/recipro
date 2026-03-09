from __future__ import annotations

import json

from .models import ImprovementTask

_PLAN_ONLY = """You are in PLAN-ONLY mode. Read files freely but do NOT edit, create, delete, or run any commands. Return only the JSON below."""

_JSON_SHAPE = json.dumps({
    "tasks": [{
        "title": "Short title",
        "description": "What and why.",
        "steps": ["Concrete step referencing file:function"],
        "files": ["path/to/file.py"],
        "expected_change": "One-sentence outcome.",
        "manual_actions": [],
    }]
}, ensure_ascii=False, indent=2)

_TEST_REQUIREMENTS = """
Write tests for every change: happy paths (expected behavior) and unhappy paths (invalid inputs, missing config, error conditions, edge cases). Use the project's existing test framework.
"""

_TEST_REVIEW = """
Check test coverage: are both happy and unhappy paths tested? List specific missing test cases in findings if not.
"""


# -- Planner prompts --

def scan_prompt(*, max_improvements: int, focus: str | None) -> str:
    if focus:
        return focused_scan_prompt(max_improvements=max_improvements, focus=focus)
    return general_scan_prompt(max_improvements=max_improvements)


def focused_scan_prompt(*, max_improvements: int, focus: str) -> str:
    return f"""
You are Recipro's planner. {_PLAN_ONLY}

User directive:
{focus}

Read the relevant source files, then break this into up to {max_improvements} concrete tasks. Each step must reference specific files and functions.

Return strict JSON:
{_JSON_SHAPE}
""".strip()


def general_scan_prompt(*, max_improvements: int) -> str:
    return f"""
You are Recipro's planner. {_PLAN_ONLY}

Scan the repo for up to {max_improvements} high-impact improvements. Prioritize: bugs, correctness gaps, security issues, maintainability.

Constraints: no architecture rewrites, no dependency upgrades, no migrations, no API changes.

Each step must reference specific files and functions. Return strict JSON:
{_JSON_SHAPE}
""".strip()


# -- Builder prompts --

def implement_prompt(
    task: ImprovementTask,
    *,
    feedback: list[str],
    add_tests: bool = True,
) -> str:
    feedback_block = "\n".join(f"- {item}" for item in feedback) if feedback else "- None"
    steps_block = "\n".join(f"{i}. {s}" for i, s in enumerate(task.steps, 1)) if task.steps else "- Use your judgment."
    files_block = ", ".join(task.files) if task.files else "unknown"
    test_block = _TEST_REQUIREMENTS if add_tests else ""
    return f"""
Implement this improvement in the current repo.

Task: {task.title}
{task.description}

Steps:
{steps_block}

Files: {files_block}

Feedback to address:
{feedback_block}

Constraints: no public API changes, no dependency upgrades, no git commands.
{test_block}
Return strict JSON:
{{
  "summary": "what you did",
  "changed_files": ["path/to/file.py"],
  "tests_ran": ["pytest tests/test_x.py"],
  "manual_actions": []
}}
""".strip()


def verify_prompt(task: ImprovementTask, feedback: list[str]) -> str:
    feedback_block = "\n".join(f"- {item}" for item in feedback) if feedback else "- None"
    return f"""
The implementation for "{task.title}" is reviewed and approved. Verify it passes all checks.

Previous failures to fix:
{feedback_block}

Run lint and tests. Fix any issues. Return strict JSON:
{{
  "status": "pass" or "fail",
  "summary": "what you did",
  "failures": ["failure description"]
}}
""".strip()


def push_pr_prompt(
    task: ImprovementTask,
    summary: str,
    changed_files: list[str],
    *,
    auto_merge: bool = False,
) -> str:
    files_block = ", ".join(changed_files) if changed_files else "(check git status)"
    merge_step = "\n5. Merge the PR with `gh pr merge --squash --delete-branch`." if auto_merge else ""
    return f"""
Ship this as a pull request.

Task: {task.title}
Summary: {summary}
Changed files: {files_block}

Steps:
1. Create a descriptive branch.
2. Stage and commit all changes.
3. Push to origin.
4. Create PR with `gh pr create`.{merge_step}

Do NOT run tests or lint — already passed.

Return strict JSON:
{{
  "pr_url": "full PR URL",
  "branch_name": "branch name",
  "commit_message": "commit message",
  "merged": {"true" if auto_merge else "false"}
}}
""".strip()


# -- Critic prompts --

def review_prompt(focus: str | None = None, add_tests: bool = True) -> str:
    if focus:
        return focused_review_prompt(focus=focus, add_tests=add_tests)
    return general_review_prompt(add_tests=add_tests)


def focused_review_prompt(*, focus: str, add_tests: bool = True) -> str:
    test_block = _TEST_REVIEW if add_tests else ""
    return f"""
Review the changes against this directive:
{focus}

Run `git diff` to see changes. Check: does the implementation fully address the directive? Any bugs, regressions, or missed requirements?
{test_block}
Ignore style nitpicks. Return strict JSON:
{{
  "status": "pass" or "fail",
  "summary": "short explanation",
  "findings": ["concrete fix needed"],
  "manual_actions": []
}}
""".strip()


def general_review_prompt(*, add_tests: bool = True) -> str:
    test_block = _TEST_REVIEW if add_tests else ""
    return f"""
Review the changes. Run `git diff`. Focus on: correctness bugs, regressions, unsafe behavior, missing edge cases.
{test_block}
Ignore style nitpicks. Return strict JSON:
{{
  "status": "pass" or "fail",
  "summary": "short explanation",
  "findings": ["concrete fix needed"],
  "manual_actions": []
}}
""".strip()
