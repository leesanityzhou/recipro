from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from .base import Backend
from ..utils import CommandError, extract_json_value

log = logging.getLogger("recipro.backend.claude")

# Suppress noisy SDK transport logs ("Using bundled Claude Code CLI: ...")
logging.getLogger("claude_agent_sdk._internal.transport").setLevel(logging.WARNING)


def run_sdk_query(
    prompt: str,
    *,
    cwd: Path,
    model: str | None = None,
    permission_mode: str = "bypassPermissions",
    session_id: str | None = None,
) -> tuple[str, str | None]:
    """Synchronous wrapper around the SDK async query(). Returns (result_text, session_id)."""
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
        TextBlock,
        query,
    )

    options = ClaudeAgentOptions(
        cwd=cwd,
        model=model,
        permission_mode=permission_mode,
        resume=session_id,
        stderr=lambda line: log.debug("[sdk] %s", line.rstrip()),
    )

    async def _run() -> tuple[str, str | None]:
        from ..ambient import get_agent as get_ambient, is_verbose

        ambient = get_ambient()
        verbose = is_verbose()
        text_parts: list[str] = []
        result_text = ""
        result_sid: str | None = None

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
                        line = f"  [claude] {block.text.strip()}\n"
                        if verbose:
                            sys.stderr.write(line)
                            sys.stderr.flush()
                        if ambient and ambient.available:
                            ambient.add(line)

            elif isinstance(message, ResultMessage):
                if message.is_error:
                    raise CommandError(
                        ["claude-sdk"], 1,
                        message.result or "", message.result or "",
                    )
                result_text = message.result or ""
                result_sid = message.session_id

        # ResultMessage.result can be empty (e.g. plan mode);
        # fall back to accumulated TextBlock text.
        if not result_text and text_parts:
            result_text = "\n".join(text_parts)

        return result_text, result_sid

    # SDK uses anyio internally; create a fresh event loop to avoid conflicts.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    except CommandError:
        raise
    except Exception as exc:
        from claude_agent_sdk import CLINotFoundError, ProcessError, CLIConnectionError

        if isinstance(exc, CLINotFoundError):
            raise SystemExit(
                "'claude' not found. Install with: npm install -g @anthropic-ai/claude-code\n"
                "Then authenticate with: claude login"
            ) from exc
        if isinstance(exc, (ProcessError, CLIConnectionError)):
            stderr = getattr(exc, "stderr", "") or str(exc)
            exit_code = getattr(exc, "exit_code", 1) or 1
            raise CommandError(
                ["claude-sdk"], exit_code, "", stderr,
            ) from exc
        raise CommandError(
            ["claude-sdk"], 1, "", str(exc),
        ) from exc
    finally:
        loop.close()


class ClaudeBackend(Backend):
    name = "claude"
    stream_key = "claude"
    default_cmd = "claude"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session_id: str | None = None

    def exec_text(self, prompt: str, cwd: Path, *, editable: bool = False, continue_session: bool = False) -> str:
        sid = self._session_id if continue_session else None
        text, new_sid = run_sdk_query(
            prompt, cwd=cwd, model=self.model,
            permission_mode="bypassPermissions", session_id=sid,
        )
        self._session_id = new_sid
        return text

    def exec_json(self, prompt: str, schema: dict[str, Any], cwd: Path, *, continue_session: bool = False) -> Any:
        text = self.exec_text(prompt, cwd, continue_session=continue_session)
        return extract_json_value(text)

    def check_auth(self) -> None:
        log.info("Checking Claude authentication...")
        try:
            run_sdk_query("echo ok", cwd=Path.cwd(), permission_mode="plan")
        except SystemExit:
            raise
        except CommandError as exc:
            stderr = exc.stderr.lower() if exc.stderr else ""
            if any(kw in stderr for kw in ("auth", "api key", "login")):
                raise SystemExit("Claude Code is not authenticated. Run: claude login") from exc
            raise SystemExit(f"Claude check failed: {exc}") from exc
