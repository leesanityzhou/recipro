from __future__ import annotations

import logging
from datetime import date, datetime

from ..agents import ClaudeAgent, CodexAgent
from ..config import AppConfig
from ..models import ImprovementTask, TaskOutcome
from ..prompts import pr_body
from ..reporting import build_report_markdown, write_report
from ..state import append_run
from ..utils import CommandError, dedupe_strings, ensure_directory, run_command
from .git_tools import GitRepo

log = logging.getLogger("recipro")


class Orchestrator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.codex = CodexAgent(config)
        self.claude = ClaudeAgent(config)
        self.git = GitRepo(config)

    def _check_auth(self) -> None:
        """Verify that codex and claude CLIs are installed and authenticated."""
        import shutil
        import subprocess

        codex_bin = self.config.codex_cmd[0]
        claude_bin = self.config.claude_cmd[0]

        if not shutil.which(codex_bin):
            raise SystemExit(
                f"'{codex_bin}' not found. Install it with: npm install -g @openai/codex\n"
                f"Then authenticate with: codex login"
            )

        if not shutil.which(claude_bin):
            raise SystemExit(
                f"'{claude_bin}' not found. Install it with: npm install -g @anthropic-ai/claude-code\n"
                f"Then authenticate with: claude login"
            )

        # Quick smoke test for codex auth
        log.info("Checking Codex authentication...")
        try:
            result = subprocess.run(
                [*self.config.codex_cmd, "exec", "--sandbox", "read-only", "echo ok"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if "auth" in stderr.lower() or "api key" in stderr.lower() or "unauthorized" in stderr.lower():
                    raise SystemExit(
                        f"Codex is not authenticated. Run: codex login"
                    )
                raise SystemExit(f"Codex check failed: {stderr or result.stdout.strip()}")
        except FileNotFoundError:
            raise SystemExit(f"'{codex_bin}' not found on PATH.")
        except subprocess.TimeoutExpired:
            log.warning("Codex auth check timed out, proceeding anyway...")

        # Quick smoke test for claude auth
        log.info("Checking Claude authentication...")
        try:
            result = subprocess.run(
                [*self.config.claude_cmd, "-p", "echo ok"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if "auth" in stderr.lower() or "api key" in stderr.lower() or "login" in stderr.lower():
                    raise SystemExit(
                        f"Claude Code is not authenticated. Run: claude login"
                    )
                raise SystemExit(f"Claude check failed: {stderr or result.stdout.strip()}")
        except FileNotFoundError:
            raise SystemExit(f"'{claude_bin}' not found on PATH.")
        except subprocess.TimeoutExpired:
            log.warning("Claude auth check timed out, proceeding anyway...")

        log.info("Both Codex and Claude authenticated successfully.")

    def run(self) -> Path:
        ensure_directory(self.config.report_dir)
        ensure_directory(self.config.memory_dir)

        self._check_auth()

        started_at = datetime.utcnow()
        repo_path = self.config.repo_path

        if not repo_path.exists():
            raise FileNotFoundError(f"Target repo does not exist: {repo_path}")

        self.git.assert_repo_exists()

        if self.config.require_clean_worktree and not self.config.dry_run:
            self.git.ensure_clean_worktree()

        log.info("Scanning repo with Codex: %s", repo_path)
        tasks = self.codex.scan_repo(repo_path)
        log.info("Codex found %d improvement task(s)", len(tasks))
        for i, task in enumerate(tasks, 1):
            log.info("  [%d] %s", i, task.title)
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

        original_ref = self.config.base_branch or self.git.current_ref()
        start_point = original_ref

        for i, task in enumerate(tasks, 1):
            log.info("Running task %d/%d: %s", i, len(tasks), task.title)
            outcome = self._run_task(task, start_point=start_point)
            outcomes.append(outcome)
            log.info("Task '%s' finished with status: %s", task.title, outcome.status)
            if outcome.status == "failed":
                break
            self.git.switch(original_ref)

        return self._finalize(started_at, outcomes)

    def _run_task(self, task: ImprovementTask, *, start_point: str) -> TaskOutcome:
        log.info("Creating branch for task: %s", task.title)
        branch_name = self.git.create_branch(task.title, start_point=start_point)
        outcome = TaskOutcome(
            task=task,
            status="failed",
            branch=branch_name,
            manual_actions=list(task.manual_actions),
        )
        feedback: list[str] = []

        try:
            for review_round in range(1, self.config.max_review_loops + 1):
                log.info("  Round %d/%d: Claude implementing...", review_round, self.config.max_review_loops)
                implementation = self.claude.implement_task(
                    self.config.repo_path,
                    task,
                    feedback,
                )
                outcome.review_rounds = review_round
                outcome.summary = implementation.summary or outcome.summary
                outcome.tests_ran = dedupe_strings(outcome.tests_ran + implementation.tests_ran)
                outcome.manual_actions = dedupe_strings(
                    outcome.manual_actions + implementation.manual_actions
                )

                if not self.git.has_changes():
                    raise RuntimeError(
                        f"Claude did not create any repository changes for task '{task.title}'."
                    )

                log.info("  Round %d/%d: running validations...", review_round, self.config.max_review_loops)
                validation_findings = self._run_validations()
                if validation_findings:
                    log.warning("  Validation failed (%d finding(s)), retrying...", len(validation_findings))
                    feedback = validation_findings
                    continue

                log.info("  Round %d/%d: Codex reviewing changes...", review_round, self.config.max_review_loops)
                review = self.codex.review_changes(self.config.repo_path)
                outcome.manual_actions = dedupe_strings(
                    outcome.manual_actions + review.manual_actions
                )

                if review.status == "pass":
                    log.info("  Review passed!")
                    break

                log.info("  Review failed (%d finding(s)), iterating...", len(review.findings))
                feedback = review.findings
                if not feedback:
                    raise RuntimeError("Codex returned fail without concrete findings.")
            else:
                raise RuntimeError(
                    f"Codex still had findings after {self.config.max_review_loops} review rounds."
                )

            outcome.changed_files = self.git.changed_files()
            commit_message = f"{self.config.commit_prefix}: {task.title}"
            outcome.commit_sha = self.git.commit_all(commit_message)

            if self.config.push_branch:
                self.git.push_branch(branch_name)

            if self.config.github_auto_pr:
                outcome.pr_url = self.git.create_pr(
                    branch_name,
                    task.title,
                    pr_body(outcome),
                )
                if self.config.github_auto_merge and outcome.pr_url:
                    self.git.merge_pr(outcome.pr_url)

            outcome.status = "completed"
            return outcome
        except (RuntimeError, CommandError) as error:
            outcome.error = str(error)
            return outcome

    def _run_validations(self) -> list[str]:
        findings: list[str] = []
        for command in self.config.validation_commands:
            try:
                run_command(command, cwd=self.config.repo_path, check=True)
            except CommandError as error:
                findings.append(
                    f"Validation command failed: {' '.join(command)}\n{error.stderr.strip() or error.stdout.strip()}"
                )
        return findings

    def _finalize(self, started_at: datetime, outcomes: list[TaskOutcome]) -> Path:
        log.info("Finalizing run and generating report...")
        run_date = date.today()
        markdown = build_report_markdown(
            run_date=run_date,
            repo_path=self.config.repo_path,
            outcomes=outcomes,
            dry_run=self.config.dry_run,
        )

        if self.config.report_with_codex and outcomes:
            try:
                summary = self.codex.summarize_report(
                    self.config.repo_path,
                    run_date.isoformat(),
                    outcomes,
                )
                markdown = self._render_codex_summary(run_date, summary)
            except Exception:
                pass

        report_path = write_report(self.config, run_date, markdown)
        append_run(
            self.config.state_path,
            {
                "started_at": started_at.isoformat(timespec="seconds") + "Z",
                "finished_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "repo_path": str(self.config.repo_path),
                "dry_run": self.config.dry_run,
                "report_path": str(report_path),
                "outcomes": [outcome.to_dict() for outcome in outcomes],
            },
        )
        return report_path

    def _render_codex_summary(self, run_date: date, summary: dict[str, list[str]]) -> str:
        sections = [
            ("Improvements Completed", summary.get("improvements_completed", [])),
            ("Files Changed", summary.get("files_changed", [])),
            ("Risks", summary.get("risks", [])),
            ("Manual Actions Required", summary.get("manual_actions_required", [])),
        ]
        lines = [f"# Recipro Report - {run_date.isoformat()}", ""]
        for title, items in sections:
            lines.append(f"# {title}")
            lines.append("")
            if items:
                lines.extend(f"- {item}" for item in items)
            else:
                lines.append("- None")
            lines.append("")
        return "\n".join(lines).strip() + "\n"
