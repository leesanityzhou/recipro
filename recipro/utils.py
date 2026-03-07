from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Sequence


class CommandError(RuntimeError):
    def __init__(self, command: Sequence[str], returncode: int, stdout: str, stderr: str):
        command_text = " ".join(command)
        message = f"Command failed ({returncode}): {command_text}"
        if stderr.strip():
            message = f"{message}\n{stderr.strip()}"
        super().__init__(message)
        self.command = tuple(command)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    ensure_directory(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def dedupe_strings(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def slugify(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered)
    return lowered.strip("-") or "task"


def extract_json_value(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise ValueError("Expected JSON output, received empty text")

    decoder = json.JSONDecoder()
    for start, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[start:])
            return value
        except JSONDecodeError:
            continue

    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fenced != stripped:
        return extract_json_value(fenced)

    raise ValueError(f"Could not parse JSON from response: {text[:400]}")


def _codex_stream_filter(line: str, state: dict[str, Any]) -> str | None:
    """Only show lines from 'codex' sections, skip user/exec/header noise."""
    stripped = line.strip()
    if stripped in ("user", "codex", "exec"):
        state["section"] = stripped
        return None
    if stripped == "--------" or stripped.startswith("mcp startup:"):
        return None
    section = state.get("section")
    if section is None:
        # Header block (before first section)
        return None
    if section == "codex" and stripped:
        return f"  [codex] {stripped}\n"
    return None


def _claude_stream_filter(line: str, state: dict[str, Any]) -> str | None:
    """Show claude output lines with a prefix."""
    stripped = line.strip()
    if stripped:
        return f"  [claude] {stripped}\n"
    return None


# merge_stderr: True = merge stderr into stdout (codex puts everything on stdout)
#               False = keep stderr separate, only stream/capture stdout (claude: tool noise on stderr)
STREAM_CONFIGS: dict[str, dict[str, Any]] = {
    "codex": {"filter": _codex_stream_filter, "merge_stderr": True},
    "claude": {"filter": _claude_stream_filter, "merge_stderr": True},
}


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    check: bool = True,
    stream: bool | str = False,
) -> subprocess.CompletedProcess[str]:
    if not stream:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            input=input_text,
            text=True,
            capture_output=True,
        )
    else:
        import sys
        config = STREAM_CONFIGS.get(stream, {}) if isinstance(stream, str) else {}
        stream_filter = config.get("filter")
        merge_stderr = config.get("merge_stderr", True)
        filter_state: dict[str, Any] = {}
        proc = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            stdin=subprocess.PIPE if input_text else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.DEVNULL,
            text=True,
        )
        if input_text and proc.stdin:
            proc.stdin.write(input_text)
            proc.stdin.close()
        from .ambient import get_agent
        ambient = get_agent()
        stdout_lines: list[str] = []
        for line in proc.stdout:
            stdout_lines.append(line)
            if stream_filter:
                filtered = stream_filter(line, filter_state)
                if filtered:
                    if ambient and ambient.available:
                        ambient.add(filtered)
                    else:
                        sys.stderr.write(filtered)
                        sys.stderr.flush()
            else:
                if ambient and ambient.available:
                    ambient.add(line)
                else:
                    sys.stderr.write(line)
                    sys.stderr.flush()
        proc.wait()
        result = subprocess.CompletedProcess(
            args=list(command),
            returncode=proc.returncode,
            stdout="".join(stdout_lines),
            stderr="",
        )
    if check and result.returncode != 0:
        raise CommandError(command, result.returncode, result.stdout, result.stderr)
    return result

