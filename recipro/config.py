from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return ""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def load_settings(path: Path) -> dict[str, Any]:
    """Load simple key: value settings from a yaml-like file."""
    if not path.exists():
        return {}
    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        data[key.strip()] = _parse_scalar(raw_value)
    return data


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    repo_path: Path
    focus: str | None
    max_improvements: int

    planner_model: str | None
    critic_backend: str
    critic_model: str | None
    builder_backend: str
    builder_model: str | None

    dry_run: bool = False
    require_clean_worktree: bool = True
    summarize_report: bool = True
    auto_merge: bool = False

    @property
    def report_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def memory_dir(self) -> Path:
        return self.project_root / "memory"

    @property
    def state_path(self) -> Path:
        return self.memory_dir / "state.json"

    def with_overrides(self, **kwargs: Any) -> AppConfig:
        return replace(self, **kwargs)
