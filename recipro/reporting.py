from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .models import TaskOutcome
from .utils import ensure_directory


def build_report_markdown(
    *,
    started_at: datetime,
    finished_at: datetime,
    repo_path: Path,
    outcomes: list[TaskOutcome],
    dry_run: bool,
    focus: str | None,
) -> str:
    """Build an operational run report — complements the PR, does not duplicate it.

    PR description covers *what* changed and *why*.
    This report covers *how* the run went: config, process, review rounds, errors.
    """
    duration = finished_at - started_at
    mins, secs = divmod(int(duration.total_seconds()), 60)

    lines = [
        f"# Recipro Run Report",
        f"",
        f"| | |",
        f"|---|---|",
        f"| **Repository** | `{repo_path}` |",
        f"| **Started** | {started_at.strftime('%Y-%m-%d %H:%M:%S')} UTC |",
        f"| **Duration** | {mins}m {secs}s |",
        f"| **Mode** | {'Dry run' if dry_run else 'Full run'} |",
    ]
    if focus:
        lines.append(f"| **Focus** | {focus[:120]} |")
    lines.append("")

    for i, outcome in enumerate(outcomes, 1):
        status_emoji = {"completed": "PASS", "failed": "FAIL", "skipped": "SKIP"}[outcome.status]
        lines.append(f"## Task {i}: {outcome.task.title} [{status_emoji}]")
        lines.append("")

        if outcome.summary:
            lines.append(f"- **Summary**: {outcome.summary}")
        if outcome.pr_url:
            lines.append(f"- **PR**: {outcome.pr_url}")
        if outcome.branch:
            lines.append(f"- **Branch**: `{outcome.branch}`")
        if outcome.review_rounds:
            lines.append(f"- **Review rounds**: {outcome.review_rounds}")
        if outcome.changed_files:
            lines.append(f"- **Changed files**: {', '.join(f'`{f}`' for f in outcome.changed_files)}")
        if outcome.tests_ran:
            lines.append(f"- **Tests ran**: {', '.join(f'`{t}`' for t in outcome.tests_ran)}")
        if outcome.error:
            lines.append(f"- **Error**: {outcome.error}")
        if outcome.manual_actions:
            lines.append(f"- **Manual actions needed**:")
            for action in outcome.manual_actions:
                lines.append(f"  - {action}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def write_report(config: AppConfig, started_at: datetime, markdown: str) -> Path:
    ensure_directory(config.report_dir)
    timestamp = started_at.strftime("%Y%m%d-%H%M%S")
    path = config.report_dir / f"run-{timestamp}.md"
    path.write_text(markdown, encoding="utf-8")
    return path

