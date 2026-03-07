from __future__ import annotations

from datetime import date
from pathlib import Path

from .config import AppConfig
from .models import TaskOutcome
from .utils import dedupe_strings, ensure_directory


def _section(title: str, items: list[str]) -> str:
    lines = [f"# {title}", ""]
    if items:
        lines.extend(f"- {item}" for item in items)
    else:
        lines.append("- None")
    return "\n".join(lines)


def build_report_markdown(
    *,
    run_date: date,
    repo_path: Path,
    outcomes: list[TaskOutcome],
    dry_run: bool,
) -> str:
    completed = [f"{item.task.title}: {item.summary or item.task.description}" for item in outcomes if item.status == "completed"]
    skipped = [f"{item.task.title}: {item.summary or 'Skipped.'}" for item in outcomes if item.status == "skipped"]
    failed = [f"{item.task.title}: {item.error or 'Failed.'}" for item in outcomes if item.status == "failed"]
    files_changed = dedupe_strings(path for item in outcomes for path in item.changed_files)
    manual_actions = dedupe_strings(action for item in outcomes for action in item.manual_actions)
    risks = []

    if dry_run:
        risks.append("Dry run mode was enabled; no repository mutations, pushes, or PRs were performed.")
    if failed:
        risks.append("At least one task failed and Recipro stopped without cleaning up the task branch.")
    if not completed and not failed and not skipped:
        risks.append("Codex did not return any actionable improvements.")

    report = [
        f"# Recipro Report - {run_date.isoformat()}",
        "",
        f"Repository: `{repo_path}`",
        "",
        _section("Improvements Completed", completed),
        "",
        _section("Files Changed", files_changed),
        "",
        _section("Risks", risks + failed),
        "",
        _section("Manual Actions Required", manual_actions),
    ]

    if skipped:
        report.extend(["", _section("Skipped Tasks", skipped)])

    return "\n".join(report).strip() + "\n"


def write_report(config: AppConfig, run_date: date, markdown: str) -> Path:
    ensure_directory(config.report_dir)
    path = config.report_dir / f"{run_date.isoformat()}.md"
    path.write_text(markdown, encoding="utf-8")
    return path

