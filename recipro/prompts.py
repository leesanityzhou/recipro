from __future__ import annotations

import json

from .models import ImprovementTask


def scan_prompt(*, max_improvements: int, focus: str | None) -> str:
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
    json_shape = json.dumps(example, ensure_ascii=False, indent=2)

    read_only_rule = """
CRITICAL: You are operating in PLAN-ONLY mode — simulating Claude's plan permission mode.
This means you must behave exactly as if --permission-mode plan were active:
- You may READ any files to understand the codebase.
- You must NOT create, edit, delete, or modify any files.
- You must NOT run git commands, tests, linters, or any commands that change state.
- You must NOT propose a "plan for review" — execute your analysis NOW and return the result.
- Your ONLY output should be the JSON task list specified below. No prose, no explanations, no preamble."""

    if focus:
        return f"""
You are the planner agent in Recipro, a multi-agent code-improvement loop.
{read_only_rule}

The user has given you a specific directive. Read it carefully, understand the full intent, and produce up to {max_improvements} concrete tasks that a builder agent should execute to fulfill it.

User directive:
{focus}

Inspect the repository in the current working directory. Break the directive down into actionable improvement tasks. Each task should be specific enough for another agent to implement without further clarification.

Return strict JSON only, matching this shape:
{json_shape}
""".strip()

    return f"""
You are the planner agent in Recipro, a multi-agent code-improvement loop.
{read_only_rule}

Inspect the repository in the current working directory and return up to {max_improvements} safe, high-impact improvements.

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
- prefer tasks that another agent can complete locally without outside systems
- touch as many files as needed to do the job correctly

Return strict JSON only, matching this shape:
{json_shape}
""".strip()


def implement_prompt(
    task: ImprovementTask,
    *,
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
- keep the patch safe and correct
- touch as many files as needed to do the job properly
- do not change public APIs unless the task explicitly requires it
- do not upgrade dependencies
- do not run git commands (branching and committing is handled externally)
- if you run tests, keep them as small and relevant as possible

After editing the repository, return strict JSON only:
{{
  "summary": "short summary of the implementation",
  "changed_files": ["path/to/file.py"],
  "tests_ran": ["pytest tests/test_example.py"],
  "manual_actions": []
}}
""".strip()


def review_prompt(focus: str | None = None) -> str:
    if focus:
        return f"""
You are the critic agent in Recipro.

The user gave the following directive:
{focus}

A builder agent has made changes to the repository to fulfill this directive.
Run `git diff` to see exactly what was changed, then review the changes.

Your job is to ensure the user's intent has been fully and correctly implemented. Check:
- Does the implementation actually address what the user asked for?
- Are there any parts of the directive that were missed or misunderstood?
- Are there correctness bugs, regressions, or unsafe behavior in the changes?

Ignore style-only nitpicks. Focus on whether the directive was fulfilled correctly.

Return strict JSON only:
{{
  "status": "pass" or "fail",
  "summary": "short explanation",
  "findings": ["concrete fix 1", "concrete fix 2"],
  "manual_actions": []
}}

Use "pass" only when the directive is fully and correctly implemented.
""".strip()

    return """
You are the critic agent in Recipro.

A builder agent has made changes to the repository.
Run `git diff` to see exactly what was changed, then review the changes.

Focus only on material issues:
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


def verify_prompt(task: ImprovementTask, feedback: list[str]) -> str:
    feedback_block = "\n".join(f"- {item}" for item in feedback) if feedback else "- None"
    return f"""
You are the builder agent in Recipro. The implementation has been reviewed and approved.
Before shipping, you must verify the code passes all checks.

Task: {task.title}

Previous test/lint failures to fix:
{feedback_block}

Steps:
1. If there are failures listed above, fix them first.
2. Run linting and formatting checks if the project has them configured (e.g. ruff, eslint, black, prettier). Fix any issues.
3. Run the full test suite if the project has one (e.g. pytest, jest). Fix any failures.

Return strict JSON only:
{{
  "status": "pass" or "fail",
  "summary": "what you did",
  "failures": ["description of failure 1", "description of failure 2"]
}}

Use "pass" only when all lint checks and tests pass (or the project has none configured).
""".strip()


def push_pr_prompt(task: ImprovementTask, summary: str, changed_files: list[str], *, auto_merge: bool = False) -> str:
    files_block = "\n".join(f"- {f}" for f in changed_files) if changed_files else "- (check git status)"
    merge_step = "\n5. Merge the PR using `gh pr merge --squash --delete-branch`." if auto_merge else ""
    return f"""
You are the builder agent in Recipro. The implementation has been reviewed, tested, and approved.
Now ship it as a pull request.

Task: {task.title}
Description: {task.description}
Implementation summary: {summary}

Changed files:
{files_block}

Steps to follow in order:
1. Create a new git branch with a clear, descriptive name.
2. Stage and commit all changes with a good commit message.
3. Push the branch to origin.
4. Create a pull request using `gh pr create` with a clear title and description.{merge_step}

Do NOT run tests or lint — they have already passed.

Return strict JSON only:
{{
  "pr_url": "the full URL of the created PR",
  "branch_name": "the branch name you used",
  "commit_message": "the commit message you used",
  "merged": {"true" if auto_merge else "false"}
}}
""".strip()

