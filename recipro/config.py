from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import ast
import json
import shlex
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

    if value.startswith(("[", "{", '"', "'")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return ast.literal_eval(value)

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    return value


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_list_key: str | None = None

    for index, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue

        stripped = raw_line.strip()
        if stripped.startswith("#"):
            continue

        if raw_line.startswith((" ", "\t")):
            if current_list_key is None or not stripped.startswith("- "):
                raise ValueError(f"Unsupported YAML structure on line {index}: {raw_line}")
            if data[current_list_key] is None:
                data[current_list_key] = []
            data[current_list_key].append(_parse_scalar(stripped[2:]))
            continue

        current_list_key = None
        if ":" not in raw_line:
            raise ValueError(f"Expected key/value pair on line {index}: {raw_line}")

        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value == "":
            data[key] = None
            current_list_key = key
            continue

        data[key] = _parse_scalar(value)

    return data


def _resolve_path(base_dir: Path, raw_value: str) -> Path:
    path = Path(str(raw_value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _parse_command(raw_value: Any, default: str) -> tuple[str, ...]:
    if raw_value is None:
        return (default,)

    if isinstance(raw_value, str):
        parts = tuple(shlex.split(raw_value))
        return parts or (default,)

    if isinstance(raw_value, list):
        parts = tuple(str(item) for item in raw_value)
        return parts or (default,)

    raise ValueError(f"Unsupported command value: {raw_value!r}")


def _parse_command_list(raw_value: Any) -> tuple[tuple[str, ...], ...]:
    if raw_value in (None, ""):
        return ()

    if not isinstance(raw_value, list):
        raise ValueError("validation_commands must be a YAML list of command strings")

    commands: list[tuple[str, ...]] = []
    for item in raw_value:
        parts = tuple(shlex.split(str(item)))
        if parts:
            commands.append(parts)
    return tuple(commands)


def _parse_arg_list(raw_value: Any) -> tuple[str, ...]:
    if raw_value in (None, ""):
        return ()
    if not isinstance(raw_value, list):
        raise ValueError("Expected a YAML list of strings")
    return tuple(str(item) for item in raw_value)


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    project_root: Path
    repo_path: Path
    max_improvements: int
    max_review_loops: int
    max_files_per_change: int
    codex_cmd: tuple[str, ...]
    claude_cmd: tuple[str, ...]
    gh_cmd: tuple[str, ...]
    branch_prefix: str
    commit_prefix: str
    base_branch: str | None
    dry_run: bool
    require_clean_worktree: bool
    push_branch: bool
    github_auto_pr: bool
    github_auto_merge: bool
    github_merge_mode: str
    report_with_codex: bool
    claude_permission_mode: str
    codex_extra_args: tuple[str, ...]
    claude_extra_args: tuple[str, ...]
    validation_commands: tuple[tuple[str, ...], ...]
    report_dir: Path
    memory_dir: Path

    @property
    def state_path(self) -> Path:
        return self.memory_dir / "state.json"

    def with_overrides(self, **kwargs: Any) -> "AppConfig":
        return replace(self, **kwargs)


def load_config(path: Path) -> AppConfig:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Config file not found: {resolved}")

    raw = _parse_simple_yaml(resolved.read_text(encoding="utf-8"))
    project_root = resolved.parent

    config = AppConfig(
        config_path=resolved,
        project_root=project_root,
        repo_path=_resolve_path(project_root, raw.get("repo_path", ".")),
        max_improvements=int(raw.get("max_improvements", 3)),
        max_review_loops=int(raw.get("max_review_loops", 5)),
        max_files_per_change=int(raw.get("max_files_per_change", 5)),
        codex_cmd=_parse_command(raw.get("codex_cmd"), "codex"),
        claude_cmd=_parse_command(raw.get("claude_cmd"), "claude"),
        gh_cmd=_parse_command(raw.get("gh_cmd"), "gh"),
        branch_prefix=str(raw.get("branch_prefix", "recipro/")),
        commit_prefix=str(raw.get("commit_prefix", "improve")),
        base_branch=raw.get("base_branch"),
        dry_run=bool(raw.get("dry_run", True)),
        require_clean_worktree=bool(raw.get("require_clean_worktree", True)),
        push_branch=bool(raw.get("push_branch", False)),
        github_auto_pr=bool(raw.get("github_auto_pr", False)),
        github_auto_merge=bool(raw.get("github_auto_merge", False)),
        github_merge_mode=str(raw.get("github_merge_mode", "squash")),
        report_with_codex=bool(raw.get("report_with_codex", True)),
        claude_permission_mode=str(raw.get("claude_permission_mode", "acceptEdits")),
        codex_extra_args=_parse_arg_list(raw.get("codex_extra_args", [])),
        claude_extra_args=_parse_arg_list(raw.get("claude_extra_args", [])),
        validation_commands=_parse_command_list(raw.get("validation_commands")),
        report_dir=_resolve_path(project_root, raw.get("report_dir", "reports")),
        memory_dir=_resolve_path(project_root, raw.get("memory_dir", "memory")),
    )

    if config.github_auto_pr and not config.push_branch:
        raise ValueError("github_auto_pr requires push_branch: true")
    if config.github_auto_merge and not config.github_auto_pr:
        raise ValueError("github_auto_merge requires github_auto_pr: true")

    return config
