from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from ..ambient import get_agent as get_ambient
from ..backends import create_backend
from ..config import AppConfig
from ..models import ImplementationResult, ImprovementTask, ReviewResult, TaskOutcome
from ..prompts import implement_prompt, push_pr_prompt, review_prompt, scan_prompt, verify_prompt
from ..reporting import build_report_markdown, write_report
from ..state import append_run
from ..utils import CommandError, dedupe_strings, ensure_directory, extract_json_value, run_command
from .git_tools import GitRepo

log = logging.getLogger("recipro")

REVIEW_SCHEMA = {
    "type": "object",
    "required": ["status", "summary", "findings", "manual_actions"],
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail"]},
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
        "manual_actions": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

MAX_VERIFY_ROUNDS = 5

class Orchestrator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.critic = create_backend(config, "critic")
        self.builder = create_backend(config, "builder")
        self.git = GitRepo(config)

    def _check_auth(self) -> None:
        from ..backends.claude import ClaudeBackend
        checked: set[str] = set()
        # Planner is always Claude — check it first
        planner_check = ClaudeBackend(model=None, extra_args=())
        planner_check.check_auth()
        checked.add("claude")
        for backend in (self.critic, self.builder):
            if backend.name not in checked:
                backend.check_auth()
                checked.add(backend.name)
        log.info("All backends authenticated successfully.")

    def _plan_tasks(self) -> list[ImprovementTask]:
        """Use Claude plan mode to analyze the repo and generate tasks."""
        prompt = scan_prompt(
            max_improvements=self.config.max_improvements,
            focus=self.config.focus,
        )
        model_args = ("--model", self.config.planner_model) if self.config.planner_model else ()
        command = [
            "claude", "-p",
            "--dangerously-skip-permissions",
            *model_args,
            prompt,
        ]
        result = run_command(command, cwd=self.config.repo_path, check=True, stream="claude")
        ambient = get_ambient()
        if ambient:
            ambient.track_cost("planner", self.config.planner_model or "sonnet", len(prompt), len(result.stdout))
        payload = extract_json_value(result.stdout)
        if isinstance(payload, dict) and "tasks" in payload:
            items = payload["tasks"]
        elif isinstance(payload, list):
            items = payload
        else:
            raise RuntimeError(f"Unexpected planner output: {str(payload)[:200]}")
        tasks = [
            task for item in items
            if (task := ImprovementTask.from_dict(item)).title and task.description
        ][: self.config.max_improvements]
        return tasks

    def run(self) -> tuple[Path, list[TaskOutcome]]:
        ensure_directory(self.config.report_dir)
        ensure_directory(self.config.memory_dir)

        self._check_auth()

        started_at = datetime.utcnow()
        repo_path = self.config.repo_path

        if not repo_path.exists():
            raise FileNotFoundError(f"Target repo does not exist: {repo_path}")

        self.git.ensure_repo_exists()

        if self.config.require_clean_worktree and not self.config.dry_run:
            self.git.ensure_clean_worktree()

        if not self.config.dry_run and self.git.has_remote():
            log.info("Pulling latest changes from remote...")
            try:
                self.git.pull()
            except CommandError:
                log.warning("git pull failed (no remote or diverged history), continuing with local HEAD")

        log.info("Planning improvements with Claude (plan mode): %s", repo_path)
        tasks = self._plan_tasks()
        log.info("Planner found %d improvement task(s)", len(tasks))
        for i, task in enumerate(tasks, 1):
            log.info("  [%d] %s", i, task.title)
        ambient = get_ambient()
        if ambient:
            details = "\n".join(f"- {t.title}: {t.description}" for t in tasks)
            ambient.stage(f"Plan ready. Tasks:\n{details}")

        outcomes: list[TaskOutcome] = []

        if self.config.dry_run:
            for task in tasks:
                outcomes.append(
                    TaskOutcome(
                        task=task,
                        status="skipped",
                        summary="Dry run only. Recipro planned this task but did not modify the repository.",
                        manual_actions=list(task.manual_actions),
                    )
                )
            return self._finalize(started_at, outcomes)

        for i, task in enumerate(tasks, 1):
            log.info("Running task %d/%d: %s", i, len(tasks), task.title)
            outcome = self._run_task(task)
            outcomes.append(outcome)
            log.info("Task '%s' finished with status: %s", task.title, outcome.status)
            if outcome.status == "failed":
                break

        return self._finalize(started_at, outcomes)

    def _run_task(self, task: ImprovementTask) -> TaskOutcome:
        outcome = TaskOutcome(
            task=task,
            status="failed",
            manual_actions=list(task.manual_actions),
        )
        feedback: list[str] = []

        try:
            review_round = 0
            while True:
                review_round += 1
                log.info("  Round %d: %s implementing...", review_round, self.builder.name)

                is_retry = review_round > 1
                if is_retry:
                    ambient = get_ambient()
                    if ambient:
                        findings_detail = "\n".join(f"  - {f}" for f in feedback)
                        ambient.stage(f"Builder is reworking based on critic feedback:\n{findings_detail}")
                prompt = implement_prompt(task, feedback=feedback)
                result_text = self.builder.exec_text(
                    prompt, self.config.repo_path, editable=True,
                    continue_session=is_retry,
                )
                ambient = get_ambient()
                if ambient:
                    ambient.track_cost("builder", self.builder.model, len(prompt), len(result_text))

                try:
                    impl_payload = extract_json_value(result_text)
                    if isinstance(impl_payload, dict):
                        implementation = ImplementationResult.from_dict(impl_payload)
                    else:
                        implementation = ImplementationResult(summary=result_text.strip())
                except ValueError:
                    implementation = ImplementationResult(summary=result_text.strip())

                outcome.review_rounds = review_round
                outcome.summary = implementation.summary or outcome.summary
                outcome.tests_ran = dedupe_strings(outcome.tests_ran + implementation.tests_ran)
                outcome.manual_actions = dedupe_strings(
                    outcome.manual_actions + implementation.manual_actions
                )

                if not self.git.has_changes():
                    raise RuntimeError(
                        f"Builder did not create any repository changes for task '{task.title}'."
                    )

                log.info("  Round %d: %s reviewing changes...", review_round, self.critic.name)
                ambient = get_ambient()
                if ambient:
                    files = ", ".join(implementation.changed_files) if implementation.changed_files else "unknown files"
                    ambient.stage(f"Implementation done: {implementation.summary}\nChanged: {files}")
                review_prompt_text = review_prompt(self.config.focus)
                review_payload = self.critic.exec_json(
                    review_prompt_text, REVIEW_SCHEMA, self.config.repo_path,
                )
                ambient = get_ambient()
                if ambient:
                    ambient.track_cost("critic", self.critic.model, len(review_prompt_text), len(str(review_payload)))
                review = ReviewResult.from_dict(review_payload)
                outcome.manual_actions = dedupe_strings(
                    outcome.manual_actions + review.manual_actions
                )

                if review.status == "pass":
                    log.info("  Review passed!")
                    ambient = get_ambient()
                    if ambient:
                        ambient.stage(f"Critic approved: {review.summary}")
                    break

                log.info("  Review failed (%d finding(s)), iterating...", len(review.findings))
                ambient = get_ambient()
                if ambient:
                    findings_detail = "\n".join(f"  - {f}" for f in review.findings)
                    ambient.stage(f"Critic rejected. Issues found:\n{findings_detail}")
                feedback = review.findings
                if not feedback:
                    raise RuntimeError("Critic returned fail without concrete findings.")

            # Verify: run lint/tests, loop back to builder on failure
            test_feedback: list[str] = []
            for verify_round in range(1, MAX_VERIFY_ROUNDS + 1):
                log.info("  Verify round %d: running lint/tests...", verify_round)
                vp = verify_prompt(task, test_feedback)
                verify_text = self.builder.exec_text(vp, self.config.repo_path, editable=True, continue_session=True)
                ambient = get_ambient()
                if ambient:
                    ambient.track_cost("builder", self.builder.model, len(vp), len(verify_text))
                try:
                    vp_payload = extract_json_value(verify_text)
                    if isinstance(vp_payload, dict) and vp_payload.get("status") == "pass":
                        log.info("  Lint/tests passed!")
                        break
                    failures = vp_payload.get("failures", []) if isinstance(vp_payload, dict) else []
                    test_feedback = failures if failures else [vp_payload.get("summary", "Tests failed")]
                    log.info("  Lint/tests failed (%d issue(s)), sending back to builder...", len(test_feedback))
                except ValueError:
                    test_feedback = ["Could not determine test results, please re-run tests"]
                    log.info("  Could not parse verify result, retrying...")
            else:
                log.warning("  Lint/tests did not pass after %d rounds, proceeding anyway.", MAX_VERIFY_ROUNDS)

            outcome.changed_files = self.git.changed_files()

            # Push PR (lint/tests already handled above)
            log.info("  %s pushing PR...", self.builder.name)
            pr_prompt_text = push_pr_prompt(task, outcome.summary, outcome.changed_files, auto_merge=self.config.auto_merge)
            pr_text = self.builder.exec_text(
                pr_prompt_text, self.config.repo_path, editable=True,
                continue_session=True,
            )
            ambient = get_ambient()
            if ambient:
                ambient.track_cost("builder", self.builder.model, len(pr_prompt_text), len(pr_text))
            try:
                pr_payload = extract_json_value(pr_text)
                if isinstance(pr_payload, dict):
                    outcome.pr_url = pr_payload.get("pr_url")
                    outcome.branch = pr_payload.get("branch_name", outcome.branch)
                    outcome.commit_sha = pr_payload.get("commit_sha")
            except ValueError:
                log.warning("  Could not parse PR result, continuing...")

            outcome.status = "completed"
            if outcome.pr_url:
                log.info("  PR created: %s", outcome.pr_url)
                ambient = get_ambient()
                if ambient:
                    changed = ", ".join(outcome.changed_files[:5]) if outcome.changed_files else "unknown"
                    ambient.stage(f"PR shipped: {outcome.pr_url}\nFiles touched: {changed}\nRounds: {outcome.review_rounds}")
            return outcome
        except (RuntimeError, CommandError) as error:
            outcome.error = str(error)
            return outcome

    def _finalize(self, started_at: datetime, outcomes: list[TaskOutcome]) -> tuple[Path, list[TaskOutcome]]:
        log.info("Finalizing run and generating report...")
        finished_at = datetime.utcnow()
        markdown = build_report_markdown(
            started_at=started_at,
            finished_at=finished_at,
            repo_path=self.config.repo_path,
            outcomes=outcomes,
            dry_run=self.config.dry_run,
            focus=self.config.focus,
        )

        report_path = write_report(self.config, started_at, markdown)
        append_run(
            self.config.state_path,
            {
                "started_at": started_at.isoformat(timespec="seconds") + "Z",
                "finished_at": finished_at.isoformat(timespec="seconds") + "Z",
                "repo_path": str(self.config.repo_path),
                "dry_run": self.config.dry_run,
                "report_path": str(report_path),
                "outcomes": [outcome.to_dict() for outcome in outcomes],
            },
        )
        return report_path, outcomes
