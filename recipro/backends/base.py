from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Backend(ABC):
    """Base class for CLI backends (codex, claude, etc.)."""

    name: str
    stream_key: str
    default_cmd: str  # default CLI command name

    def __init__(self, *, cmd: tuple[str, ...] | None = None, model: str | None, extra_args: tuple[str, ...]):
        self.cmd = cmd or (self.default_cmd,)
        self.model = model
        self.extra_args = extra_args

    @abstractmethod
    def exec_json(self, prompt: str, schema: dict[str, Any], cwd: Path) -> Any:
        """Execute prompt and return structured JSON."""

    @abstractmethod
    def exec_text(self, prompt: str, cwd: Path, *, editable: bool = False) -> str:
        """Execute prompt and return text. If editable=True, allow file modifications."""

    @abstractmethod
    def check_auth(self) -> None:
        """Verify CLI is installed and authenticated. Raise SystemExit on failure."""
