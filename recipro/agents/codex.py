from __future__ import annotations

import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ..config import AppConfig
from ..models import ImprovementTask, ReviewResult, TaskOutcome
from ..prompts import report_prompt, review_prompt, scan_prompt
from ..utils import extract_json_value, run_command

log = logging.getLogger("recipro.codex")


class CodexAgent:
    def __init__(self, config: AppConfig):
        self.config = config

    def scan_repo(self, repo_path: Path) -> list[ImprovementTask]:
        schema = {
            "type": "object",
            "required": ["tasks"],
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["title", "description", "files", "expected_change", "manual_actions"],
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "files": {"type": "array", "items": {"type": "string"}},
                            "expected_change": {"type": "string"},
                            "manual_actions": {"type": "array", "items": {"type": "string"}},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        }
        payload = self._exec_json(
            repo_path=repo_path,
            prompt=scan_prompt(
                max_improvements=self.config.max_improvements,
                max_files_per_change=self.config.max_files_per_change,
            ),
            schema=schema,
            sandbox="read-only",
        )
        tasks = [ImprovementTask.from_dict(item) for item in payload["tasks"]]
        return [task for task in tasks if task.title and task.description][: self.config.max_improvements]

    def review_changes(self, repo_path: Path) -> ReviewResult:
        schema = {
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
        payload = self._exec_json(
            repo_path=repo_path,
            prompt=review_prompt(),
            schema=schema,
            sandbox="read-only",
        )
        return ReviewResult.from_dict(payload)

    def summarize_report(self, repo_path: Path, run_date: str, outcomes: list[TaskOutcome]) -> dict[str, Any]:
        schema = {
            "type": "object",
            "required": [
                "improvements_completed",
                "files_changed",
                "risks",
                "manual_actions_required",
            ],
            "properties": {
                "improvements_completed": {"type": "array", "items": {"type": "string"}},
                "files_changed": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
                "manual_actions_required": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        }
        return self._exec_json(
            repo_path=repo_path,
            prompt=report_prompt(outcomes, str(repo_path), run_date),
            schema=schema,
            sandbox="read-only",
        )

    def _exec_json(
        self,
        *,
        repo_path: Path,
        prompt: str,
        schema: dict[str, Any],
        sandbox: str,
    ) -> Any:
        with TemporaryDirectory(prefix="recipro-codex-") as temp_dir:
            temp_path = Path(temp_dir)
            schema_path = temp_path / "schema.json"
            output_path = temp_path / "output.txt"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            log.debug("Codex command: %s", " ".join(self.config.codex_cmd))
            command = [
                *self.config.codex_cmd,
                "exec",
                "--color",
                "never",
                "--sandbox",
                sandbox,
                "--skip-git-repo-check",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                *self.config.codex_extra_args,
                prompt,
            ]
            result = run_command(command, cwd=repo_path, check=True, stream="codex")
            text = output_path.read_text(encoding="utf-8") if output_path.exists() else result.stdout
            return extract_json_value(text)

