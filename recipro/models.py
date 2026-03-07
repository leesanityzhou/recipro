from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ReviewStatus = Literal["pass", "fail"]
TaskStatus = Literal["completed", "failed", "skipped"]


def _string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


@dataclass(slots=True)
class ImprovementTask:
    title: str
    description: str
    files: list[str] = field(default_factory=list)
    expected_change: str = ""
    manual_actions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImprovementTask":
        return cls(
            title=str(data.get("title", "")).strip(),
            description=str(data.get("description", "")).strip(),
            files=_string_list(data.get("files")),
            expected_change=str(data.get("expected_change", "")).strip(),
            manual_actions=_string_list(data.get("manual_actions")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReviewResult:
    status: ReviewStatus
    findings: list[str] = field(default_factory=list)
    summary: str = ""
    manual_actions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewResult":
        raw_status = str(data.get("status", "fail")).strip().lower()
        status: ReviewStatus = "pass" if raw_status == "pass" else "fail"
        return cls(
            status=status,
            findings=_string_list(data.get("findings")),
            summary=str(data.get("summary", "")).strip(),
            manual_actions=_string_list(data.get("manual_actions")),
        )


@dataclass(slots=True)
class ImplementationResult:
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    tests_ran: list[str] = field(default_factory=list)
    manual_actions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImplementationResult":
        return cls(
            summary=str(data.get("summary", "")).strip(),
            changed_files=_string_list(data.get("changed_files")),
            tests_ran=_string_list(data.get("tests_ran")),
            manual_actions=_string_list(data.get("manual_actions")),
        )


@dataclass(slots=True)
class TaskOutcome:
    task: ImprovementTask
    status: TaskStatus
    branch: str | None = None
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    tests_ran: list[str] = field(default_factory=list)
    manual_actions: list[str] = field(default_factory=list)
    review_rounds: int = 0
    pr_url: str | None = None
    commit_sha: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["task"] = self.task.to_dict()
        return data

