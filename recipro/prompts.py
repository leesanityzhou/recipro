from __future__ import annotations

from .models import ImprovementTask

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
You are Recipro's planner. Read ALL relevant source files to understand the codebase thoroughly.

User directive:
{focus}

Produce up to {max_improvements} concrete improvement(s). For each, describe:
- What the problem is and why it matters
- Which specific files and functions are involved
- Exactly what to change (reference file:function by name, not vague goals)

Be specific. A builder agent will implement your plan verbatim.
""".strip()


def general_scan_prompt(*, max_improvements: int) -> str:
    return f"""
You are Recipro's planner. Scan the entire repo thoroughly — read source files, configs, and tests.

Identify up to {max_improvements} high-impact improvement(s).
Prioritize: bugs, correctness gaps, security issues, maintainability.
Constraints: no architecture rewrites, no dependency upgrades, no migrations, no API changes.

For each improvement, describe:
- What the problem is and why it matters
- Which specific files and functions are involved
- Exactly what to change (reference file:function by name, not vague goals)

Be specific. A builder agent will implement your plan verbatim.
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
Do NOT over-engineer. Make the minimum changes needed to solve the task. No unnecessary abstractions, no premature generalization, no refactoring beyond what is required.
{test_block}
Testing scope: only run tests directly related to the files you changed. Do NOT run the full test suite — that happens in a separate verification step.

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

Run the full lint and test suite. Fix any issues caused by the implementation. Return strict JSON:
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

Run `git diff` to see changes. Check: does the implementation fully address the directive? Any bugs or regressions in the changed code?

SCOPE CONSTRAINT: Only report issues that are directly within the scope of the directive above. Do NOT expand scope to unrelated code, pre-existing issues, or improvements beyond what was asked. If the changes correctly address the directive, pass the review.
Do NOT demand over-engineering. Accept minimal, correct solutions. Do not request unnecessary abstractions, extra configurability, or refactoring that goes beyond the task.
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
Review the changes. Run `git diff`. Focus on: correctness bugs, regressions, unsafe behavior in the changed code.

SCOPE CONSTRAINT: Only report issues directly caused by or within the changed code. Do NOT flag pre-existing issues, unrelated code, or improvements beyond the scope of the current task. If the changes are correct and don't introduce bugs, pass the review.
Do NOT demand over-engineering. Accept minimal, correct solutions. Do not request unnecessary abstractions, extra configurability, or refactoring that goes beyond the task.
{test_block}
Ignore style nitpicks. Return strict JSON:
{{
  "status": "pass" or "fail",
  "summary": "short explanation",
  "findings": ["concrete fix needed"],
  "manual_actions": []
}}
""".strip()
