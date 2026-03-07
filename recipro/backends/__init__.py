from __future__ import annotations

from typing import Any

from .base import Backend
from .claude import ClaudeBackend
from .codex import CodexBackend

__all__ = ["Backend", "ClaudeBackend", "CodexBackend", "create_backend"]

BACKEND_CLASSES: dict[str, type[Backend]] = {
    "codex": CodexBackend,
    "claude": ClaudeBackend,
}


def create_backend(config: Any, role: str) -> Backend:
    """Create a backend instance for a given role ('critic' or 'builder')."""
    backend_name = getattr(config, f"{role}_backend")
    model = getattr(config, f"{role}_model")

    cls = BACKEND_CLASSES.get(backend_name)
    if cls is None:
        raise ValueError(
            f"Unknown backend: {backend_name!r}. Available: {', '.join(BACKEND_CLASSES)}"
        )

    return cls(model=model, extra_args=())
