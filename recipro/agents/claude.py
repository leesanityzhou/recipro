from __future__ import annotations

import logging
from pathlib import Path

from ..config import AppConfig
from ..models import ImplementationResult, ImprovementTask
from ..prompts import implement_prompt
from ..utils import extract_json_value, run_command

log = logging.getLogger("recipro.claude")


class ClaudeAgent:
    def __init__(self, config: AppConfig):
        self.config = config

    def implement_task(
        self,
        repo_path: Path,
        task: ImprovementTask,
        feedback: list[str],
    ) -> ImplementationResult:
        prompt = implement_prompt(
            task,
            feedback=feedback,
        )
        model_args = ["--model", self.config.claude_model] if self.config.claude_model else []
        command = [
            *self.config.claude_cmd,
            "-p",
            "--permission-mode",
            self.config.claude_permission_mode,
            *model_args,
            *self.config.claude_extra_args,
            prompt,
        ]
        log.info("Calling Claude to implement: %s", task.title)
        result = run_command(command, cwd=repo_path, check=True, stream="claude")
        log.info("Claude finished implementing: %s", task.title)

        try:
            payload = extract_json_value(result.stdout)
            if isinstance(payload, dict):
                return ImplementationResult.from_dict(payload)
        except ValueError:
            pass

        return ImplementationResult(summary=result.stdout.strip())

