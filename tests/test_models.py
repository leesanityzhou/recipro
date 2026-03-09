from __future__ import annotations

from recipro.models import (
    ImprovementTask,
    ImplementationResult,
    ReviewResult,
    TaskOutcome,
)


class TestImprovementTask:
    def test_from_dict_full(self):
        data = {
            "title": "Fix auth",
            "description": "Add token validation",
            "steps": ["Step 1", "Step 2"],
            "files": ["auth.py"],
            "expected_change": "All endpoints require auth",
            "manual_actions": ["Set API_KEY env var"],
        }
        task = ImprovementTask.from_dict(data)
        assert task.title == "Fix auth"
        assert task.steps == ["Step 1", "Step 2"]
        assert task.files == ["auth.py"]
        assert task.manual_actions == ["Set API_KEY env var"]

    def test_from_dict_minimal(self):
        task = ImprovementTask.from_dict({"title": "Fix", "description": "Desc"})
        assert task.title == "Fix"
        assert task.steps == []
        assert task.files == []

    def test_from_dict_strips_whitespace(self):
        task = ImprovementTask.from_dict({"title": "  hello  ", "description": " world "})
        assert task.title == "hello"
        assert task.description == "world"

    def test_from_dict_empty_values(self):
        task = ImprovementTask.from_dict({})
        assert task.title == ""
        assert task.description == ""

    def test_roundtrip(self):
        task = ImprovementTask(title="T", description="D", steps=["s1"], files=["f.py"])
        data = task.to_dict()
        restored = ImprovementTask.from_dict(data)
        assert restored.title == task.title
        assert restored.steps == task.steps


class TestReviewResult:
    def test_pass(self):
        r = ReviewResult.from_dict({"status": "pass", "summary": "LGTM"})
        assert r.status == "pass"
        assert r.findings == []

    def test_fail_with_findings(self):
        r = ReviewResult.from_dict({
            "status": "fail",
            "findings": ["missing null check", "no error handling"],
        })
        assert r.status == "fail"
        assert len(r.findings) == 2

    def test_unknown_status_defaults_to_fail(self):
        r = ReviewResult.from_dict({"status": "maybe"})
        assert r.status == "fail"

    def test_missing_status_defaults_to_fail(self):
        r = ReviewResult.from_dict({})
        assert r.status == "fail"

    def test_case_insensitive(self):
        r = ReviewResult.from_dict({"status": "PASS"})
        assert r.status == "pass"


class TestImplementationResult:
    def test_from_dict(self):
        r = ImplementationResult.from_dict({
            "summary": "Added auth",
            "changed_files": ["a.py", "b.py"],
            "tests_ran": ["pytest"],
        })
        assert r.summary == "Added auth"
        assert len(r.changed_files) == 2

    def test_empty(self):
        r = ImplementationResult.from_dict({})
        assert r.summary == ""
        assert r.changed_files == []


class TestTaskOutcome:
    def test_to_dict(self):
        task = ImprovementTask(title="T", description="D")
        outcome = TaskOutcome(task=task, status="completed", pr_url="https://github.com/pr/1")
        data = outcome.to_dict()
        assert data["status"] == "completed"
        assert data["task"]["title"] == "T"
        assert data["pr_url"] == "https://github.com/pr/1"
