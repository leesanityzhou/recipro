from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

_agent: AmbientAgent | None = None
_verbose: bool = False


def get_agent() -> AmbientAgent | None:
    return _agent


def is_verbose() -> bool:
    return _verbose


def init_agent(
    provider: str | None = None,
    model: str | None = None,
    focus: str | None = None,
    verbose: bool = False,
) -> AmbientAgent:
    global _agent, _verbose
    _verbose = verbose
    _agent = AmbientAgent(provider=provider, model=model, focus=focus)
    return _agent


PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "env_key": "OPENAI_API_KEY",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "models": [
            ("gpt-4o-mini", "Fast, cheap"),
            ("gpt-4o", "More capable"),
        ],
        "default_model": "gpt-4o-mini",
    },
    "gemini": {
        "env_key": "GEMINI_API_KEY",
        "api_url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "models": [
            ("gemini-2.0-flash", "Fast, cheap"),
            ("gemini-2.5-pro", "Most capable"),
        ],
        "default_model": "gemini-2.0-flash",
    },
}

# Rough pricing: (input $/1M tokens, output $/1M tokens)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "o4-mini": (1.10, 4.40),
    "o3": (2.00, 8.00),
    "gpt-5.4": (5.00, 20.00),
    "sonnet": (3.00, 15.00),
    "opus": (15.00, 75.00),
    "haiku": (0.25, 1.25),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
}


def available_providers() -> list[str]:
    return [name for name, cfg in PROVIDERS.items() if os.environ.get(cfg["env_key"])]


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~3.5 chars/token for mixed content."""
    return max(1, len(text) // 4)


def _detect_language(text: str) -> str:
    """Detect the human language in text by looking for non-ASCII script characters."""
    import unicodedata
    counts: dict[str, int] = {}
    for ch in text:
        if ch.isascii():
            continue
        try:
            name = unicodedata.name(ch, "")
        except ValueError:
            continue
        if name.startswith("CJK") or name.startswith("HANGUL"):
            script = "CJK"
        elif "HIRAGANA" in name or "KATAKANA" in name:
            script = "Japanese"
        else:
            script = name.split()[0]
        counts[script] = counts.get(script, 0) + 1
    if not counts:
        return "English"
    top = max(counts, key=counts.get)  # type: ignore[arg-type]
    mapping = {"CJK": "Chinese", "HANGUL": "Korean", "ARABIC": "Arabic"}
    return mapping.get(top, top)


class AmbientAgent:
    SYSTEM_PROMPT = """You narrate Recipro, a multi-agent code improvement tool (Planner → Builder → Critic → commit/PR).

You receive [STAGE] events and raw agent outputs. The user already sees stage logs like "Planner found 3 tasks". Do NOT repeat that. Instead, extract CONCRETE details from the raw agent output that the user can't see:

Focus on:
- Specific file names, function names, or line numbers being changed
- The actual approach or technique the agent chose (e.g. "adding HMAC middleware to routes.py" not "implementing security improvements")
- Exact errors, test failures, or lint issues encountered
- Surprising decisions or trade-offs the agent is making

Rules:
- 1-2 sentences max. Be specific or say nothing.
- Use real names from the code (files, functions, variables, error messages)
- NEVER give vague summaries like "implementing improvements" or "making progress"
- If the raw output has no new concrete details, respond with just: "..."
- Match the user's language if their directive is not in English"""

    FLUSH_INTERVAL = 15
    MIN_BUFFER_LINES = 3
    MAX_FLUSH_INTERVAL = 120
    MAX_BUFFER_LINES = 400
    MAX_CONTEXT_LINES = 80
    MAX_CONTEXT_CHARS = 12_000
    REQUEST_TIMEOUT = 45

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        focus: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.focus = focus
        self.api_key = ""
        if provider and provider in PROVIDERS:
            cfg = PROVIDERS[provider]
            self.api_key = os.environ.get(cfg["env_key"], "")
            self.model = model or cfg["default_model"]
        self._buffer: list[str] = []
        self._reported: list[str] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._current_interval = self.FLUSH_INTERVAL
        self._consecutive_failures = 0
        self._disabled = False
        self._last_flush_time: float = 0.0
        self._flushing = False  # prevents concurrent flushes
        # Cost tracking
        self._ambient_tokens = {"prompt": 0, "completion": 0}
        self._agent_costs: list[dict[str, Any]] = []
        self._start_time: float = 0.0

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.provider)

    def start(self) -> None:
        if not self.available:
            return
        # Health check: verify API key works before starting the loop
        success, text = self._call_llm_probe()
        if not success:
            sys.stderr.write("\033[33m[ambient] Narrator disabled: API health check failed on startup.\033[0m\n")
            self._disabled = True
            return
        sys.stderr.write(f"\033[36m[narrator] Online — using {self.provider}/{self.model}\033[0m\n")
        self._start_time = time.time()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _call_llm_probe(self) -> tuple[bool, str]:
        """Minimal API call to verify connectivity and auth."""
        return self._ask_llm(["[STAGE] Health check: narrator starting up"])

    def stop(self) -> None:
        self._running = False
        if self.available:
            self._flush(force=True)

    def add(self, message: str) -> None:
        if not message.strip():
            return
        with self._lock:
            self._buffer.append(message.strip())
            if len(self._buffer) > self.MAX_BUFFER_LINES:
                overflow = len(self._buffer) - self.MAX_BUFFER_LINES
                self._buffer = (
                    [f"[ambient] dropped {overflow} older log line(s) due to buffer limits"]
                    + self._buffer[-self.MAX_BUFFER_LINES + 1 :]
                )

    def stage(self, event: str) -> None:
        """Record a high-level stage event (always included, triggers flush).

        Flush runs in a separate thread so it never blocks the orchestrator.
        Respects cooldown to avoid rapid API calls that trigger rate limits.
        """
        with self._lock:
            self._buffer.append(f"[STAGE] {event}")
            # Skip flush if in backoff or recently flushed (cooldown = current interval)
            since_last = time.time() - self._last_flush_time
            if since_last < self._current_interval:
                return
        threading.Thread(target=self._flush, kwargs={"force": True}, daemon=True).start()

    def track_cost(self, role: str, model: str | None, input_chars: int, output_chars: int) -> None:
        """Record an estimated cost for a main agent call."""
        model_key = model or "unknown"
        input_tokens = _estimate_tokens("x" * input_chars)
        output_tokens = _estimate_tokens("x" * output_chars)
        pricing = MODEL_PRICING.get(model_key, (0, 0))
        cost = (input_tokens * pricing[0] + output_tokens * pricing[1]) / 1_000_000
        self._agent_costs.append({
            "role": role,
            "model": model_key,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": cost,
        })

    def cost_summary(self) -> str:
        """Return a formatted cost estimate string."""
        # Ambient agent cost
        ambient_pricing = MODEL_PRICING.get(self.model or "", (0, 0))
        ambient_cost = (
            self._ambient_tokens["prompt"] * ambient_pricing[0]
            + self._ambient_tokens["completion"] * ambient_pricing[1]
        ) / 1_000_000

        # Main agent costs
        agent_total = sum(c["estimated_cost"] for c in self._agent_costs)

        total = ambient_cost + agent_total
        if total < 0.001:
            return ""

        lines = []
        # Group by role
        by_role: dict[str, float] = {}
        for c in self._agent_costs:
            by_role[c["role"]] = by_role.get(c["role"], 0) + c["estimated_cost"]
        for role, cost in by_role.items():
            if cost >= 0.001:
                lines.append(f"    {role}: ~${cost:.3f}")
        if ambient_cost >= 0.001:
            lines.append(f"    ambient: ~${ambient_cost:.4f}")
        lines.append(f"    total: ~${total:.3f}")
        return "\n".join(lines)

    def summarize(self) -> str | None:
        """Generate a final human-readable run summary."""
        if not self.available or self._disabled:
            return None
        if not self._reported:
            return None

        elapsed = time.time() - self._start_time if self._start_time else 0
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)

        cost_info = self.cost_summary()
        cost_block = f"\n\nEstimated costs:\n{cost_info}" if cost_info else ""

        lang_hint = ""
        if self.focus:
            lang_hint = f"\n\nThe user's original directive (respond in the same language):\n{self.focus[:500]}"

        prompt = (
            "You are summarizing a Recipro run for the user. "
            "Here is everything you reported during the run:\n"
            + "\n".join(f"- {r}" for r in self._reported)
            + f"\n\nRun duration: {minutes}m{seconds}s"
            + cost_block
            + lang_hint
            + "\n\nWrite a brief, friendly summary (3-5 sentences) of what happened. "
            "Include the cost estimate if available. "
            "End with any important next steps or warnings."
        )

        response = self._call_llm_raw(prompt)
        return response.strip() if response and response.strip() else None

    # -- Internal machinery --

    def _system_prompt(self) -> str:
        base = self.SYSTEM_PROMPT
        if self.focus:
            lang = _detect_language(self.focus)
            base += (
                f"\n\nThe user's directive contains text in {lang}. "
                f"You MUST respond in {lang}, regardless of other languages in the input "
                f"(error logs, code, etc. may be in English — ignore those for language detection).\n"
                f"Directive:\n{self.focus[:300]}"
            )
        return base

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._current_interval)
            self._flush()

    def _flush(self, force: bool = False) -> None:
        if self._disabled:
            with self._lock:
                self._buffer.clear()
            return
        with self._lock:
            if self._flushing:
                return  # another thread is already flushing
            if not self._buffer:
                return
            if not force and len(self._buffer) < self.MIN_BUFFER_LINES:
                return
            new_messages = self._buffer[:]
            self._buffer.clear()
            self._flushing = True

        try:
            self._last_flush_time = time.time()
            success, response = self._ask_llm(new_messages)
        finally:
            self._flushing = False
        if not success:
            with self._lock:
                self._buffer = new_messages + self._buffer
                if len(self._buffer) > self.MAX_BUFFER_LINES:
                    self._buffer = self._buffer[-self.MAX_BUFFER_LINES :]
            return

        if response and response.strip():
            text = response.strip()
            sys.stderr.write(f"\n\033[36m  [narrator] {text}\033[0m\n")
            sys.stderr.flush()
            self._reported.append(text)

    def _record_transient_failure(self, label: str, detail: str) -> None:
        """Backoff on transient errors (429, timeout) without counting toward disable."""
        self._current_interval = min(self._current_interval * 2, self.MAX_FLUSH_INTERVAL)
        sys.stderr.write(f"\033[33m[ambient] {label}: {detail} (backoff to {self._current_interval}s)\033[0m\n")

    def _record_persistent_failure(self, label: str, detail: str) -> None:
        """Count toward disable on persistent errors (auth, bad model, server error)."""
        self._consecutive_failures += 1
        sys.stderr.write(f"\033[33m[ambient] {label}: {detail}\033[0m\n")
        if self._consecutive_failures >= 5:
            self._disabled = True
            sys.stderr.write("\033[33m[ambient] Too many persistent failures, narrator disabled.\033[0m\n")

    def _truncate_logs(self, logs: list[str]) -> str:
        if not logs:
            return ""

        recent_logs = logs[-self.MAX_CONTEXT_LINES :]
        kept: list[str] = []
        total_chars = 0
        truncated = max(0, len(logs) - len(recent_logs))

        for line in reversed(recent_logs):
            projected = total_chars + len(line) + 1
            if kept and projected > self.MAX_CONTEXT_CHARS:
                truncated += 1
                continue
            kept.append(line)
            total_chars = projected

        kept.reverse()
        body = "\n".join(kept)
        if truncated:
            body = f"[ambient] omitted {truncated} older log line(s) for brevity\n{body}"
        return body

    def _build_user_msg(self, new_logs: list[str]) -> str:
        reported_ctx = ""
        if self._reported:
            recent = self._reported[-10:]
            reported_ctx = "\n\nYou already told the user:\n" + "\n".join(
                f"- {r}" for r in recent
            )
        compact_logs = self._truncate_logs(new_logs)
        return (
            f"{reported_ctx}\n\n"
            f"New agent output:\n"
            + compact_logs
            + "\n\nGive the user a brief status update based on the above."
        )

    def _ask_llm(self, new_logs: list[str]) -> tuple[bool, str]:
        if self.provider == "openai":
            return self._call_openai(self._system_prompt(), self._build_user_msg(new_logs))
        if self.provider == "gemini":
            return self._call_gemini(self._system_prompt(), self._build_user_msg(new_logs))
        return True, ""

    def _call_llm_raw(self, prompt: str) -> str:
        """Single-shot call for summarize etc."""
        if self.provider == "openai":
            success, text = self._call_openai("You are a helpful assistant.", prompt)
            return text if success else ""
        if self.provider == "gemini":
            success, text = self._call_gemini("You are a helpful assistant.", prompt)
            return text if success else ""
        return ""

    def _http_error_details(self, exc: urllib.error.HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    def _call_openai(self, system: str, user: str) -> tuple[bool, str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 300,
            "temperature": 0.3,
        }
        req = urllib.request.Request(
            PROVIDERS["openai"]["api_url"],
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
                result = json.loads(resp.read())
                self._current_interval = self.FLUSH_INTERVAL
                self._consecutive_failures = 0
                # Track token usage
                usage = result.get("usage", {})
                self._ambient_tokens["prompt"] += usage.get("prompt_tokens", 0)
                self._ambient_tokens["completion"] += usage.get("completion_tokens", 0)
                choices = result.get("choices", [])
                if choices:
                    return True, choices[0].get("message", {}).get("content", "")
                return True, ""
        except urllib.error.HTTPError as exc:
            details = self._http_error_details(exc)
            if exc.code in (401, 403):
                self._disabled = True
                sys.stderr.write(f"\033[33m[ambient] OpenAI auth error ({exc.code}): {details}\033[0m\n")
            elif exc.code == 429:
                if "quota" in details.lower() or "billing" in details.lower() or "exceeded" in details.lower():
                    self._disabled = True
                    sys.stderr.write(f"\033[33m[ambient] OpenAI quota exceeded, narrator disabled: {details}\033[0m\n")
                else:
                    self._record_transient_failure("OpenAI rate limited", details or str(exc))
            else:
                self._record_persistent_failure("OpenAI error", f"{exc} {details}")
        except (TimeoutError, urllib.error.URLError):
            self._record_transient_failure("OpenAI timeout", "request timed out")
        except Exception as exc:
            self._record_persistent_failure("OpenAI error", str(exc))
        return False, ""

    def _call_gemini(self, system: str, user: str) -> tuple[bool, str]:
        prompt = f"{system}\n{user}"
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 300, "temperature": 0.3},
        }
        url = PROVIDERS["gemini"]["api_url"].format(model=self.model) + f"?key={self.api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
                result = json.loads(resp.read())
                self._current_interval = self.FLUSH_INTERVAL
                self._consecutive_failures = 0
                # Track token usage
                usage_meta = result.get("usageMetadata", {})
                self._ambient_tokens["prompt"] += usage_meta.get("promptTokenCount", 0)
                self._ambient_tokens["completion"] += usage_meta.get("candidatesTokenCount", 0)
                candidates = result.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return True, parts[0].get("text", "")
                return True, ""
        except urllib.error.HTTPError as exc:
            details = self._http_error_details(exc)
            if exc.code in (401, 403):
                self._disabled = True
                sys.stderr.write(f"\033[33m[ambient] Gemini auth error ({exc.code}): {details}\033[0m\n")
            elif exc.code == 429:
                if "quota" in details.lower() or "billing" in details.lower() or "exceeded" in details.lower():
                    self._disabled = True
                    sys.stderr.write(f"\033[33m[ambient] Gemini quota exceeded, narrator disabled: {details}\033[0m\n")
                else:
                    self._record_transient_failure("Gemini rate limited", details or str(exc))
            else:
                self._record_persistent_failure("Gemini error", f"{exc} {details}")
        except (TimeoutError, urllib.error.URLError):
            self._record_transient_failure("Gemini timeout", "request timed out")
        except Exception as exc:
            self._record_persistent_failure("Gemini error", str(exc))
        return False, ""
