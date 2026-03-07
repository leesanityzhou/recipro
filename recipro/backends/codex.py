from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .base import Backend
from ..utils import extract_json_value, run_command

log = logging.getLogger("recipro.backend.codex")


class CodexBackend(Backend):
    name = "codex"
    stream_key = "codex"
    default_cmd = "codex"

    def exec_json(self, prompt: str, schema: dict[str, Any], cwd: Path) -> Any:
        with TemporaryDirectory(prefix="recipro-codex-") as temp_dir:
            temp_path = Path(temp_dir)
            schema_path = temp_path / "schema.json"
            output_path = temp_path / "output.txt"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            model_args = ("--model", self.model) if self.model else ()
            command = [
                *self.cmd,
                "exec",
                "--color", "never",
                "--sandbox", "read-only",
                "--skip-git-repo-check",
                "--output-schema", str(schema_path),
                "--output-last-message", str(output_path),
                *model_args,
                *self.extra_args,
                prompt,
            ]
            result = run_command(command, cwd=cwd, check=True, stream=self.stream_key)
            text = output_path.read_text(encoding="utf-8") if output_path.exists() else result.stdout
            return extract_json_value(text)

    def exec_text(self, prompt: str, cwd: Path, *, editable: bool = False) -> str:
        """Builder role: full sandbox access + web search for references."""
        sandbox = "danger-full-access" if editable else "read-only"
        model_args = ("--model", self.model) if self.model else ()
        search_args = ("--search",) if editable else ()
        command = [
            *self.cmd,
            "exec",
            "--color", "never",
            "--sandbox", sandbox,
            "--skip-git-repo-check",
            *search_args,
            *model_args,
            *self.extra_args,
            prompt,
        ]
        result = run_command(command, cwd=cwd, check=True, stream=self.stream_key)
        return result.stdout

    def check_auth(self) -> None:
        if not shutil.which(self.cmd[0]):
            raise SystemExit(
                f"'{self.cmd[0]}' not found. Install with: npm install -g @openai/codex\n"
                f"Then authenticate with: codex login"
            )
        log.info("Checking Codex authentication...")
        try:
            result = subprocess.run(
                [*self.cmd, "exec", "--sandbox", "read-only", "echo ok"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if any(kw in stderr.lower() for kw in ("auth", "api key", "unauthorized")):
                    raise SystemExit("Codex is not authenticated. Run: codex login")
                raise SystemExit(f"Codex check failed: {stderr or result.stdout.strip()}")
        except FileNotFoundError:
            raise SystemExit(f"'{self.cmd[0]}' not found on PATH.")
        except subprocess.TimeoutExpired:
            log.warning("Codex auth check timed out, proceeding anyway...")
