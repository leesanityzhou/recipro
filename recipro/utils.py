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


_FAIL_SIGNALS = re.compile(
    r"\b(fail(?:ed|ure|s)?|error(?:s)?|broken|not pass(?:ing|ed)?|cannot|exception|crash(?:ed|es)?)\b",
    re.IGNORECASE,
)
_PASS_SIGNALS = re.compile(
    r"\b(pass(?:ed|es|ing)?|success(?:ful)?|no (?:issues?|errors?|failures?)|all clear|lgtm|clean)\b",
    re.IGNORECASE,
)


def infer_status(text: str) -> str:
    """Infer pass/fail from natural language using signal-word scoring."""
    fail_score = len(_FAIL_SIGNALS.findall(text))
    pass_score = len(_PASS_SIGNALS.findall(text))
    return "pass" if pass_score > fail_score else "fail"


def parse_llm_response(text: str, model_cls: type | None = None, *, label: str = "") -> dict[str, Any] | Any:
    """Unified LLM response parser.

    1. Try to extract JSON.
    2. If JSON found and model_cls has from_dict, return model_cls.from_dict(payload).
    3. If JSON not found, return a minimal dict with status inferred from text.
    4. Always logs when falling back.
    """
    import logging
    _log = logging.getLogger("recipro.parse")

    # Try JSON first
    try:
        payload = extract_json_value(text)
        if model_cls is not None and hasattr(model_cls, "from_dict") and isinstance(payload, dict):
            return model_cls.from_dict(payload)
        return payload
    except ValueError:
        pass

    # Fallback: infer from text
    status = infer_status(text)
    _log.debug("JSON parse failed for %s, inferred status=%s from text", label or "response", status)

    if model_cls is not None and hasattr(model_cls, "from_dict"):
        return model_cls.from_dict({"status": status, "summary": text.strip()[:500]})

    return {"status": status, "summary": text.strip()[:500]}


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
        from .ambient import get_agent, is_verbose
        ambient = get_agent()
        verbose = is_verbose()
        stdout_lines: list[str] = []
        for line in proc.stdout:
            stdout_lines.append(line)
            if stream_filter:
                filtered = stream_filter(line, filter_state)
                if filtered:
                    if verbose:
                        sys.stderr.write(filtered)
                        sys.stderr.flush()
                    if ambient and ambient.available:
                        ambient.add(filtered)
            else:
                if verbose:
                    sys.stderr.write(line)
                    sys.stderr.flush()
                if ambient and ambient.available:
                    ambient.add(line)
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

