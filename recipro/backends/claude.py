from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import Backend
from ..utils import extract_json_value, run_command

log = logging.getLogger("recipro.backend.claude")


class ClaudeBackend(Backend):
    name = "claude"
    stream_key = "claude"
    default_cmd = "claude"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session_id: str | None = None

    def _build_command(self, prompt: str, *, continue_session: bool = False) -> list[str]:
        model_args = ("--model", self.model) if self.model else ()
        resume_args: tuple[str, ...] = ()
        if continue_session and self._session_id:
            resume_args = ("--resume", self._session_id)
        return [
            *self.cmd,
            "-p",
            "--dangerously-skip-permissions",
            "--output-format", "json",
            *resume_args,
            *model_args,
            *self.extra_args,
            prompt,
        ]

    def _extract_session_id(self, raw_output: str) -> str:
        """Extract session_id and actual text from JSON output format."""
        for line in reversed(raw_output.strip().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict) and data.get("session_id"):
                    self._session_id = data["session_id"]
                    log.debug("Captured session ID: %s", self._session_id)
                    return data.get("result", "")
            except json.JSONDecodeError:
                continue
        return raw_output

    def exec_json(self, prompt: str, schema: dict[str, Any], cwd: Path, *, continue_session: bool = False) -> Any:
        command = self._build_command(prompt, continue_session=continue_session)
        result = run_command(command, cwd=cwd, check=True, stream=self.stream_key)
        text = self._extract_session_id(result.stdout)
        return extract_json_value(text)

    def exec_text(self, prompt: str, cwd: Path, *, editable: bool = False, continue_session: bool = False) -> str:
        command = self._build_command(prompt, continue_session=continue_session)
        result = run_command(command, cwd=cwd, check=True, stream=self.stream_key)
        text = self._extract_session_id(result.stdout)
        return text

    def check_auth(self) -> None:
        if not shutil.which(self.cmd[0]):
            raise SystemExit(
                f"'{self.cmd[0]}' not found. Install with: npm install -g @anthropic-ai/claude-code\n"
                f"Then authenticate with: claude login"
            )
        log.info("Checking Claude authentication...")
        try:
            result = subprocess.run(
                [*self.cmd, "-p", "echo ok"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if any(kw in stderr.lower() for kw in ("auth", "api key", "login")):
                    raise SystemExit("Claude Code is not authenticated. Run: claude login")
                raise SystemExit(f"Claude check failed: {stderr or result.stdout.strip()}")
        except FileNotFoundError:
            raise SystemExit(f"'{self.cmd[0]}' not found on PATH.")
        except subprocess.TimeoutExpired:
            log.warning("Claude auth check timed out, proceeding anyway...")
