from __future__ import annotations

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

    def exec_json(self, prompt: str, schema: dict[str, Any], cwd: Path) -> Any:
        """Critic role: read-only."""
        model_args = ("--model", self.model) if self.model else ()
        command = [
            *self.cmd,
            "-p",
            "--dangerously-skip-permissions",
            *model_args,
            *self.extra_args,
            prompt,
        ]
        result = run_command(command, cwd=cwd, check=True, stream=self.stream_key)
        return extract_json_value(result.stdout)

    def exec_text(self, prompt: str, cwd: Path, *, editable: bool = False) -> str:
        """Builder role: full permissions to edit code + web access for references."""
        model_args = ("--model", self.model) if self.model else ()
        perm_args = ("--dangerously-skip-permissions",)
        command = [
            *self.cmd,
            "-p",
            *perm_args,
            *model_args,
            *self.extra_args,
            prompt,
        ]
        result = run_command(command, cwd=cwd, check=True, stream=self.stream_key)
        return result.stdout

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
