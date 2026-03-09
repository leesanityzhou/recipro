from __future__ import annotations

from recipro.models import ImprovementTask
from recipro.prompts import implement_prompt, review_prompt, scan_prompt, verify_prompt


def _make_task(**kwargs) -> ImprovementTask:
    defaults = {"title": "Fix auth", "description": "Add token check"}
    defaults.update(kwargs)
    return ImprovementTask(**defaults)


class TestScanPrompt:
    def test_with_focus(self):
        prompt = scan_prompt(max_improvements=3, focus="Fix all SQL injection")
        assert "Fix all SQL injection" in prompt
        assert "up to 3" in prompt
        assert "builder agent" in prompt.lower()

    def test_without_focus(self):
        prompt = scan_prompt(max_improvements=1, focus=None)
        assert "up to 1" in prompt
        assert "bugs" in prompt

    def test_specificity_guidance(self):
        prompt = scan_prompt(max_improvements=1, focus=None)
        assert "file" in prompt.lower()
        assert "function" in prompt.lower()


class TestImplementPrompt:
    def test_includes_task_details(self):
        task = _make_task(steps=["Step 1", "Step 2"], files=["auth.py"])
        prompt = implement_prompt(task, feedback=[])
        assert "Fix auth" in prompt
        assert "Step 1" in prompt
        assert "auth.py" in prompt

    def test_includes_feedback(self):
        task = _make_task()
        prompt = implement_prompt(task, feedback=["missing null check"])
        assert "missing null check" in prompt

    def test_no_feedback(self):
        task = _make_task()
        prompt = implement_prompt(task, feedback=[])
        assert "- None" in prompt

    def test_add_tests_true(self):
        task = _make_task()
        prompt = implement_prompt(task, feedback=[], add_tests=True)
        assert "happy path" in prompt.lower()
        assert "unhappy path" in prompt.lower()

    def test_add_tests_false(self):
        task = _make_task()
        prompt = implement_prompt(task, feedback=[], add_tests=False)
        assert "Testing requirements" not in prompt

    def test_no_steps(self):
        task = _make_task(steps=[])
        prompt = implement_prompt(task, feedback=[])
        assert "judgment" in prompt.lower() or "your judgment" in prompt.lower()

    def test_only_related_tests(self):
        task = _make_task()
        prompt = implement_prompt(task, feedback=[])
        assert "only run tests" in prompt.lower()
        assert "directly related" in prompt.lower()


class TestReviewPrompt:
    def test_with_focus(self):
        prompt = review_prompt(focus="Fix SQL injection")
        assert "Fix SQL injection" in prompt
        assert "directive" in prompt

    def test_without_focus(self):
        prompt = review_prompt(focus=None)
        assert "correctness bugs" in prompt

    def test_add_tests_true_with_focus(self):
        prompt = review_prompt(focus="Fix bug", add_tests=True)
        assert "test coverage" in prompt.lower()
        assert "unhappy path" in prompt.lower()

    def test_add_tests_false_with_focus(self):
        prompt = review_prompt(focus="Fix bug", add_tests=False)
        assert "test coverage" not in prompt.lower()

    def test_add_tests_true_without_focus(self):
        prompt = review_prompt(focus=None, add_tests=True)
        assert "test coverage" in prompt.lower()

    def test_add_tests_false_without_focus(self):
        prompt = review_prompt(focus=None, add_tests=False)
        assert "test coverage" not in prompt.lower()

    def test_scope_constraint_with_focus(self):
        prompt = review_prompt(focus="Fix bug")
        assert "scope" in prompt.lower()
        assert "do not expand" in prompt.lower() or "do not flag" in prompt.lower()

    def test_scope_constraint_without_focus(self):
        prompt = review_prompt(focus=None)
        assert "scope" in prompt.lower()
        assert "pre-existing" in prompt.lower()


class TestVerifyPrompt:
    def test_includes_task(self):
        task = _make_task()
        prompt = verify_prompt(task, feedback=[])
        assert "Fix auth" in prompt

    def test_includes_failures(self):
        task = _make_task()
        prompt = verify_prompt(task, feedback=["test_auth failed"])
        assert "test_auth failed" in prompt

    def test_runs_full_suite(self):
        task = _make_task()
        prompt = verify_prompt(task, feedback=[])
        assert "full" in prompt.lower()
