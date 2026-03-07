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


def get_agent() -> AmbientAgent | None:
    return _agent


def init_agent(
    provider: str | None = None,
    model: str | None = None,
    focus: str | None = None,
) -> AmbientAgent:
    global _agent
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


class AmbientAgent:
    SYSTEM_PROMPT = """You are the supervisor/narrator for Recipro, a multi-agent code improvement tool.

Recipro's pipeline:
1. Planner (Claude) — reads the repo, creates improvement tasks
2. Builder — implements each task (edits code)
3. Critic — reviews the changes (code review)
4. Builder — runs lint/tests, commits, pushes PR

You receive raw agent outputs (NOT shown to the user). The user only sees mechanical stage logs. Your job: monitor agent behavior and give the user intelligent, concise status updates.

Watch for and report:
- What the agent is actually doing (summarize its actions, not raw output)
- Anomalies: agent stuck in a loop, repeating itself, contradicting itself
- Quality concerns: agent skipping important steps, making questionable decisions
- Progress milestones: meaningful completions, key findings

Rules:
- 1-2 sentences max per update
- Skip noise: file paths, CLI flags, raw JSON, tool call details
- Plain language, no jargon
- Don't repeat what you already said
- If nothing notable happened, respond with empty string"""

    FLUSH_INTERVAL = 20
    MIN_BUFFER_LINES = 5
    MAX_FLUSH_INTERVAL = 120

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
        self._start_time = time.time()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self.available:
            self._flush(force=True)

    def add(self, message: str) -> None:
        if not message.strip():
            return
        with self._lock:
            self._buffer.append(message.strip())

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
            base += (
                f"\n\nThe user's directive is in the following language — "
                f"respond in the SAME language:\n{self.focus[:300]}"
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
            if not self._buffer:
                return
            if not force and len(self._buffer) < self.MIN_BUFFER_LINES:
                return
            new_messages = self._buffer[:]
            self._buffer.clear()

        response = self._ask_llm(new_messages)
        if response and response.strip():
            text = response.strip()
            sys.stderr.write(f"\033[36m{text}\033[0m\n")
            sys.stderr.flush()
            self._reported.append(text)

    def _maybe_disable(self) -> None:
        if self._consecutive_failures >= 3:
            self._disabled = True
            sys.stderr.write("\033[33m[ambient] Too many API failures, narrator disabled.\033[0m\n")

    def _build_user_msg(self, new_logs: list[str]) -> str:
        reported_ctx = ""
        if self._reported:
            recent = self._reported[-10:]
            reported_ctx = "\n\nYou already told the user:\n" + "\n".join(
                f"- {r}" for r in recent
            )
        return (
            f"{reported_ctx}\n\n"
            f"New agent output:\n"
            + "\n".join(new_logs)
            + "\n\nWhat should the user see? (empty if nothing notable)"
        )

    def _ask_llm(self, new_logs: list[str]) -> str:
        if self.provider == "openai":
            return self._call_openai(self._system_prompt(), self._build_user_msg(new_logs))
        if self.provider == "gemini":
            return self._call_gemini(self._system_prompt(), self._build_user_msg(new_logs))
        return ""

    def _call_llm_raw(self, prompt: str) -> str:
        """Single-shot call for summarize etc."""
        if self.provider == "openai":
            return self._call_openai("You are a helpful assistant.", prompt)
        if self.provider == "gemini":
            return self._call_gemini("You are a helpful assistant.", prompt)
        return ""

    def _call_openai(self, system: str, user: str) -> str:
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
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                self._current_interval = self.FLUSH_INTERVAL
                self._consecutive_failures = 0
                # Track token usage
                usage = result.get("usage", {})
                self._ambient_tokens["prompt"] += usage.get("prompt_tokens", 0)
                self._ambient_tokens["completion"] += usage.get("completion_tokens", 0)
                choices = result.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
        except urllib.error.HTTPError as exc:
            self._consecutive_failures += 1
            if exc.code == 429:
                self._current_interval = min(self._current_interval * 2, self.MAX_FLUSH_INTERVAL)
            else:
                sys.stderr.write(f"\033[33m[ambient] OpenAI error: {exc}\033[0m\n")
            self._maybe_disable()
        except Exception as exc:
            self._consecutive_failures += 1
            sys.stderr.write(f"\033[33m[ambient] OpenAI error: {exc}\033[0m\n")
            self._maybe_disable()
        return ""

    def _call_gemini(self, system: str, user: str) -> str:
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
            with urllib.request.urlopen(req, timeout=15) as resp:
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
                        return parts[0].get("text", "")
        except urllib.error.HTTPError as exc:
            self._consecutive_failures += 1
            if exc.code == 429:
                self._current_interval = min(self._current_interval * 2, self.MAX_FLUSH_INTERVAL)
            else:
                sys.stderr.write(f"\033[33m[ambient] Gemini error: {exc}\033[0m\n")
            self._maybe_disable()
        except Exception as exc:
            self._consecutive_failures += 1
            sys.stderr.write(f"\033[33m[ambient] Gemini error: {exc}\033[0m\n")
            self._maybe_disable()
        return ""
