from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .utils import read_json, write_json


def load_state(path: Path) -> dict[str, Any]:
    state = read_json(path, {"runs": []})
    if "runs" not in state or not isinstance(state["runs"], list):
        state = {"runs": []}
    return state


def append_run(path: Path, run_record: dict[str, Any]) -> None:
    state = load_state(path)
    state["last_updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    state["runs"].append(run_record)
    write_json(path, state)

