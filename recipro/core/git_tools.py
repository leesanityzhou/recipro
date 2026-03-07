from __future__ import annotations

import re

from ..config import AppConfig
from ..utils import dedupe_strings, run_command, slugify


class GitRepo:
    def __init__(self, config: AppConfig):
        self.config = config
        self.repo_path = config.repo_path

    def assert_repo_exists(self) -> None:
        result = run_command(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.repo_path,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != "true":
            raise RuntimeError(f"Target repo is not a git repository: {self.repo_path}")

    def current_ref(self) -> str:
        result = run_command(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=self.repo_path,
            check=True,
        )
        ref = result.stdout.strip()
        if ref == "HEAD":
            return self.head_sha()
        return ref

    def head_sha(self) -> str:
        return run_command(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_path,
            check=True,
        ).stdout.strip()

    def pull(self) -> None:
        """Pull latest changes from remote."""
        run_command(
            ["git", "pull", "--ff-only"],
            cwd=self.repo_path,
            check=True,
        )

    def ensure_clean_worktree(self) -> None:
        status = self.status_lines()
        if status:
            raise RuntimeError(
                "Target repo has a dirty worktree. Commit or stash changes before running Recipro."
            )

    def status_lines(self) -> list[str]:
        result = run_command(
            ["git", "status", "--short"],
            cwd=self.repo_path,
            check=True,
        )
        return [line for line in result.stdout.splitlines() if line.strip()]

    def has_changes(self) -> bool:
        return bool(self.status_lines())

    def create_branch(self, title: str, start_point: str) -> str:
        base_name = f"recipro/{slugify(title)}"
        branch_name = base_name
        suffix = 2
        while self.branch_exists(branch_name):
            branch_name = f"{base_name}-{suffix}"
            suffix += 1

        run_command(
            ["git", "switch", "-c", branch_name, start_point],
            cwd=self.repo_path,
            check=True,
        )
        return branch_name

    def branch_exists(self, branch_name: str) -> bool:
        result = run_command(
            ["git", "show-ref", "--verify", f"refs/heads/{branch_name}"],
            cwd=self.repo_path,
            check=False,
        )
        return result.returncode == 0

    def switch(self, ref: str) -> None:
        run_command(["git", "switch", ref], cwd=self.repo_path, check=True)

    def changed_files(self) -> list[str]:
        result = run_command(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=self.repo_path,
            check=True,
        )
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not files:
            status_files = []
            for line in self.status_lines():
                path = re.split(r"\s+", line.strip(), maxsplit=1)[-1]
                status_files.append(path)
            files = status_files
        return dedupe_strings(files)

    def commit_all(self, message: str) -> str:
        run_command(["git", "add", "."], cwd=self.repo_path, check=True)
        run_command(["git", "commit", "-m", message], cwd=self.repo_path, check=True)
        return self.head_sha()

    def push_branch(self, branch_name: str) -> None:
        run_command(
            ["git", "push", "-u", "origin", branch_name],
            cwd=self.repo_path,
            check=True,
        )

    def create_pr(self, branch_name: str, title: str, body: str) -> str:
        command = [
            "gh",
            "pr",
            "create",
            "--head",
            branch_name,
            "--title",
            title,
            "--body",
            body,
        ]
        result = run_command(command, cwd=self.repo_path, check=True)
        return result.stdout.strip().splitlines()[-1].strip()

    def default_branch(self) -> str:
        """Detect the default branch (main or master)."""
        for name in ("main", "master"):
            if self.branch_exists(name):
                return name
        return "main"

    def clean_worktree(self) -> dict[str, list[str]]:
        """Reset dirty worktree: discard changes, switch to default branch, delete recipro/* branches."""
        result: dict[str, list[str]] = {"discarded": [], "deleted_branches": [], "switched_to": []}

        # 1. Discard all uncommitted changes
        status = self.status_lines()
        if status:
            run_command(["git", "checkout", "."], cwd=self.repo_path, check=False)
            run_command(["git", "clean", "-fd"], cwd=self.repo_path, check=False)
            result["discarded"] = status

        # 2. Switch to default branch
        current = self.current_ref()
        default = self.default_branch()
        if current != default:
            run_command(["git", "switch", default], cwd=self.repo_path, check=True)
            result["switched_to"] = [f"{current} → {default}"]

        # 3. Delete local recipro/* branches
        branches_out = run_command(
            ["git", "branch", "--list", "recipro/*"],
            cwd=self.repo_path,
            check=True,
        )
        for line in branches_out.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if branch:
                run_command(["git", "branch", "-D", branch], cwd=self.repo_path, check=False)
                result["deleted_branches"].append(branch)

        return result

    def merge_pr(self, pr_ref: str) -> None:
        command = ["gh", "pr", "merge", pr_ref, "--squash"]
        run_command(command, cwd=self.repo_path, check=True)
