from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

DATA_DIR = Path.home() / ".recipro"

DEFAULT_SETTINGS = {
    "max_improvements": 1,
    "require_clean_worktree": True,
    "auto_merge": False,
    "verbose": False,
    "add_tests": True,
}


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


def load_settings() -> dict[str, Any]:
    """Load settings from ~/.recipro/config.yaml, merged with defaults."""
    settings = dict(DEFAULT_SETTINGS)
    path = DATA_DIR / "config.yaml"
    if not path.exists():
        return settings
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        settings[key.strip()] = _parse_scalar(raw_value)
    return settings


def save_setting(key: str, value: Any) -> None:
    """Update a single key in ~/.recipro/config.yaml, preserving other lines."""
    path = DATA_DIR / "config.yaml"
    if value is True:
        raw = "true"
    elif value is False:
        raw = "false"
    else:
        raw = str(value)

    lines: list[str] = []
    found = False
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and ":" in stripped:
                k = stripped.split(":", 1)[0].strip()
                if k == key:
                    lines.append(f"{key}: {raw}")
                    found = True
                    continue
            lines.append(line)
    if not found:
        lines.append(f"{key}: {raw}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_data_dir() -> None:
    """Create ~/.recipro/ and write default config.yaml if missing."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    config_path = DATA_DIR / "config.yaml"
    if not config_path.exists():
        config_path.write_text(
            "max_improvements: 1\n"
            "require_clean_worktree: true\n"
            "auto_merge: false\n"
            "verbose: false\n",
            encoding="utf-8",
        )


@dataclass(frozen=True)
class AppConfig:
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
    auto_merge: bool = False
    verbose: bool = False
    add_tests: bool = True

    @property
    def report_dir(self) -> Path:
        return DATA_DIR / "reports"

    @property
    def memory_dir(self) -> Path:
        return DATA_DIR / "memory"

    @property
    def state_path(self) -> Path:
        return self.memory_dir / "state.json"

    def with_overrides(self, **kwargs: Any) -> AppConfig:
        return replace(self, **kwargs)
