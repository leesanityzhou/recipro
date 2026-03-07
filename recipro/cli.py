from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import AppConfig, DATA_DIR, ensure_data_dir, load_settings

BACKENDS: list[tuple[str, str]] = [
    ("codex", "OpenAI Codex"),
    ("claude", "Anthropic Claude"),
]

MODELS: dict[str, list[tuple[str, str]]] = {
    "codex": [
        ("o4-mini", "Fast, cost-effective"),
        ("o3", "Strong reasoning"),
        ("gpt-5.4", "Most capable"),
    ],
    "claude": [
        ("sonnet", "Fast, balanced"),
        ("opus", "Most capable"),
        ("haiku", "Fastest, lightweight"),
    ],
}

PREFS_PATH = DATA_DIR / "memory" / "preferences.json"


# -- Preferences persistence --

def _load_prefs() -> dict | None:
    if not PREFS_PATH.exists():
        return None
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_prefs(prefs: dict) -> None:
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFS_PATH.write_text(json.dumps(prefs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# -- Interactive pickers --

def _pick_repo(current: str | None) -> str:
    if current:
        print(f"\n  Target repo: {current}")
        raw = input("  Change? (enter new path or press Enter to keep): ").strip()
        if raw:
            print(f"  → {raw}")
            return raw
        print(f"  → {current}")
        return current
    while True:
        raw = input("\n  Target repo path: ").strip()
        if raw:
            path = Path(raw).expanduser().resolve()
            if path.is_dir():
                print(f"  → {path}")
                return str(path)
            print(f"  Directory not found: {raw}")
        else:
            print("  Repo path is required.")


def _pick_backend(role: str, current: str) -> str:
    print(f"\n  {role.capitalize()} backend:")
    for i, (name, desc) in enumerate(BACKENDS, 1):
        marker = " <-- current" if name == current else ""
        print(f"    {i}. {name} - {desc}{marker}")
    print(f"    0. Keep current ({current})")

    while True:
        raw = input(f"  Select {role} backend [0]: ").strip()
        if raw == "" or raw == "0":
            print(f"  → {current}")
            return current
        try:
            idx = int(raw)
            if 1 <= idx <= len(BACKENDS):
                selected = BACKENDS[idx - 1][0]
                print(f"  → {selected}")
                return selected
        except ValueError:
            pass
        print("  Invalid choice, try again.")


def _pick_model(role: str, backend: str, current: str | None) -> str | None:
    choices = MODELS.get(backend, [])
    if not choices:
        return current

    default = current or choices[0][0]
    print(f"\n  {role.capitalize()} ({backend}) model:")
    for i, (model, desc) in enumerate(choices, 1):
        marker = " <-- current" if model == default else ""
        print(f"    {i}. {model} - {desc}{marker}")
    print(f"    0. Keep current ({default})")

    while True:
        raw = input(f"  Select {role} model [0]: ").strip()
        if raw == "" or raw == "0":
            print(f"  → {default}")
            return default
        try:
            idx = int(raw)
            if 1 <= idx <= len(choices):
                selected = choices[idx - 1][0]
                print(f"  → {selected}")
                return selected
        except ValueError:
            pass
        print("  Invalid choice, try again.")


def _pick_ambient() -> tuple[str | None, str | None]:
    from .ambient import PROVIDERS, available_providers

    avail = available_providers()
    if not avail:
        print("\n  Ambient narrator: disabled (no OPENAI_API_KEY or GEMINI_API_KEY)")
        return None, None

    if len(avail) == 1:
        provider = avail[0]
        print(f"\n  Ambient narrator: {provider}")
    else:
        print("\n  Ambient narrator provider:")
        for i, name in enumerate(avail, 1):
            print(f"    {i}. {name}")
        print("    0. Disable")
        while True:
            raw = input("  Select ambient provider [1]: ").strip()
            if raw == "0":
                return None, None
            if raw == "":
                provider = avail[0]
                break
            try:
                idx = int(raw)
                if 1 <= idx <= len(avail):
                    provider = avail[idx - 1]
                    break
            except ValueError:
                pass
            print("  Invalid choice, try again.")
        print(f"  → {provider}")

    models = PROVIDERS[provider]["models"]
    default = PROVIDERS[provider]["default_model"]
    print(f"  Ambient model:")
    for i, (m, desc) in enumerate(models, 1):
        marker = " <-- default" if m == default else ""
        print(f"    {i}. {m} - {desc}{marker}")
    print(f"    0. Keep default ({default})")
    while True:
        raw = input("  Select ambient model [0]: ").strip()
        if raw == "" or raw == "0":
            print(f"  → {default}")
            return provider, default
        try:
            idx = int(raw)
            if 1 <= idx <= len(models):
                selected = models[idx - 1][0]
                print(f"  → {selected}")
                return provider, selected
        except ValueError:
            pass
        print("  Invalid choice, try again.")


def _ask_focus() -> str | None:
    """Ask for focus directive every run. Empty = global scan."""
    print("\n  What should Recipro focus on?")
    print("  (Paste your directive, or press Enter for a general code scan)")
    print("  (End multi-line input with an empty line)")
    lines: list[str] = []
    while True:
        try:
            line = input("  > " if not lines else "    ")
        except EOFError:
            break
        if line.strip() == "" and lines:
            break
        if line.strip() == "" and not lines:
            return None
        lines.append(line)
    focus = "\n".join(lines).strip()
    return focus or None


# -- CLI --

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="recipro",
        description="Recipro — autonomous multi-agent code improvement.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only, no repo changes.",
    )
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="Force re-selection of backends, models, and repo.",
    )
    parser.add_argument(
        "--no-select",
        action="store_true",
        help="Skip all interactive prompts.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )
    return parser.parse_args()


# -- Main --

def main() -> int:
    from .ambient import PROVIDERS, available_providers, init_agent
    from .core.orchestrator import Orchestrator

    args = parse_args()
    ensure_data_dir()

    prefs = _load_prefs()

    need_setup = (
        not args.no_select
        and sys.stdin.isatty()
        and (prefs is None or args.reconfigure)
    )

    if need_setup:
        print("First-time setup (press Enter to keep defaults):")

        repo_path = _pick_repo(prefs.get("repo_path") if prefs else None)
        planner_model = _pick_model("planner", "claude", prefs.get("planner_model") if prefs else None)

        critic_backend = _pick_backend("critic", (prefs or {}).get("critic_backend", "codex"))
        critic_model = _pick_model("critic", critic_backend, prefs.get("critic_model") if prefs and critic_backend == (prefs or {}).get("critic_backend") else None)

        builder_backend = _pick_backend("builder", (prefs or {}).get("builder_backend", "claude"))
        builder_model = _pick_model("builder", builder_backend, prefs.get("builder_model") if prefs and builder_backend == (prefs or {}).get("builder_backend") else None)

        ambient_provider, ambient_model = _pick_ambient()

        prefs = {
            "repo_path": repo_path,
            "planner_model": planner_model,
            "critic_backend": critic_backend,
            "critic_model": critic_model,
            "builder_backend": builder_backend,
            "builder_model": builder_model,
            "ambient_provider": ambient_provider,
            "ambient_model": ambient_model,
        }
        _save_prefs(prefs)
        print(f"\n  Preferences saved to ~/.recipro/. Run --reconfigure to change later.")

    if not prefs:
        print("No preferences found. Run without --no-select first, or use --reconfigure.")
        return 1

    # Ask for focus every run (unless --no-select)
    focus: str | None = None
    if not args.no_select and sys.stdin.isatty():
        focus = _ask_focus()

    # Load base settings from ~/.recipro/config.yaml
    settings = load_settings()

    # Build config
    config = AppConfig(
        repo_path=Path(prefs["repo_path"]).expanduser().resolve(),
        focus=focus,
        max_improvements=int(settings.get("max_improvements", 1)),
        planner_model=prefs.get("planner_model"),
        critic_backend=prefs.get("critic_backend", "codex"),
        critic_model=prefs.get("critic_model"),
        builder_backend=prefs.get("builder_backend", "claude"),
        builder_model=prefs.get("builder_model"),
        dry_run=args.dry_run,
        require_clean_worktree=bool(settings.get("require_clean_worktree", True)),
        auto_merge=bool(settings.get("auto_merge", False)),
    )

    ambient = init_agent(
        provider=prefs.get("ambient_provider"),
        model=prefs.get("ambient_model"),
        focus=focus,
    )

    # Mechanical logs always go to stderr
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if ambient.available:
        ambient.start()

    orchestrator = Orchestrator(config)
    report_path, outcomes = orchestrator.run()

    if ambient.available:
        ambient.stop()
        summary = ambient.summarize()
        if summary:
            print(f"\n\033[36m{summary}\033[0m")
        costs = ambient.cost_summary()
        if costs:
            print(f"\n  Estimated costs:\n{costs}")

    print(f"\nReport written to {report_path}")
    for outcome in outcomes:
        if outcome.pr_url:
            print(f"  PR: {outcome.pr_url}")
    return 0


def _entry() -> None:
    """Entry point for console_scripts."""
    sys.exit(main())
