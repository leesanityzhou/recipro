from __future__ import annotations

import pytest

from recipro.utils import (
    CommandError,
    dedupe_strings,
    extract_json_value,
    infer_status,
    parse_llm_response,
    slugify,
    _codex_stream_filter,
    _claude_stream_filter,
)
from recipro.models import ImplementationResult


# -- extract_json_value --

class TestExtractJsonValue:
    def test_plain_object(self):
        assert extract_json_value('{"a": 1}') == {"a": 1}

    def test_plain_array(self):
        assert extract_json_value('[1, 2, 3]') == [1, 2, 3]

    def test_json_with_preamble(self):
        text = 'Here is the result:\n{"status": "pass"}'
        assert extract_json_value(text) == {"status": "pass"}

    def test_json_with_trailing_text(self):
        text = '{"x": 1} some trailing stuff'
        assert extract_json_value(text) == {"x": 1}

    def test_fenced_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        assert extract_json_value(text) == {"key": "value"}

    def test_fenced_no_lang(self):
        text = '```\n[1, 2]\n```'
        assert extract_json_value(text) == [1, 2]

    def test_nested_object(self):
        text = '{"tasks": [{"title": "fix bug", "files": ["a.py"]}]}'
        result = extract_json_value(text)
        assert result["tasks"][0]["title"] == "fix bug"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty text"):
            extract_json_value("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty text"):
            extract_json_value("   \n  ")

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="Could not parse JSON"):
            extract_json_value("just plain text with no json")

    def test_malformed_json_raises(self):
        with pytest.raises(ValueError, match="Could not parse JSON"):
            extract_json_value('{"key": }')

    def test_json_buried_deep(self):
        text = "Some preamble\nMore text\n\n" + '{"found": true}' + "\nDone."
        assert extract_json_value(text) == {"found": True}


# -- dedupe_strings --

class TestDedupeStrings:
    def test_removes_duplicates(self):
        assert dedupe_strings(["a", "b", "a", "c"]) == ["a", "b", "c"]

    def test_strips_whitespace(self):
        assert dedupe_strings(["  a  ", "a", " b "]) == ["a", "b"]

    def test_removes_empty(self):
        assert dedupe_strings(["", "  ", "a", ""]) == ["a"]

    def test_preserves_order(self):
        assert dedupe_strings(["c", "b", "a"]) == ["c", "b", "a"]

    def test_empty_input(self):
        assert dedupe_strings([]) == []

    def test_all_empty(self):
        assert dedupe_strings(["", " ", "  "]) == []


# -- slugify --

class TestSlugify:
    def test_basic(self):
        assert slugify("Fix the bug") == "fix-the-bug"

    def test_special_chars(self):
        assert slugify("Add auth/validation!") == "add-auth-validation"

    def test_multiple_separators(self):
        assert slugify("a---b___c") == "a-b-c"

    def test_leading_trailing_stripped(self):
        assert slugify("--hello--") == "hello"

    def test_empty_returns_task(self):
        assert slugify("") == "task"

    def test_all_special_returns_task(self):
        assert slugify("!!!") == "task"

    def test_unicode(self):
        result = slugify("修复 bug")
        assert result == "bug"


# -- CommandError --

class TestCommandError:
    def test_basic(self):
        err = CommandError(["git", "push"], 1, "out", "fatal: error")
        assert "git push" in str(err)
        assert "fatal: error" in str(err)
        assert err.returncode == 1

    def test_empty_stderr(self):
        err = CommandError(["ls"], 2, "out", "  ")
        assert "ls" in str(err)
        assert err.returncode == 2


# -- infer_status --

class TestInferStatus:
    def test_clear_pass(self):
        assert infer_status("All tests passed successfully") == "pass"

    def test_clear_fail(self):
        assert infer_status("3 tests failed with errors") == "fail"

    def test_mixed_signals_more_pass(self):
        assert infer_status("Tests passed, no issues found, all clean") == "pass"

    def test_mixed_signals_more_fail(self):
        assert infer_status("Tests passed but 2 errors and 1 failure found") == "fail"

    def test_no_signals_defaults_fail(self):
        assert infer_status("I did some stuff to the code") == "fail"

    def test_empty(self):
        assert infer_status("") == "fail"

    def test_success_keyword(self):
        assert infer_status("Build successful, no issues") == "pass"

    def test_lgtm(self):
        assert infer_status("LGTM, looks good") == "pass"

    def test_exception(self):
        assert infer_status("RuntimeError: exception in module X") == "fail"


# -- parse_llm_response --

class TestParseLlmResponse:
    def test_valid_json(self):
        result = parse_llm_response('{"status": "pass", "summary": "ok"}')
        assert result == {"status": "pass", "summary": "ok"}

    def test_valid_json_with_model(self):
        result = parse_llm_response(
            '{"summary": "added auth", "changed_files": ["a.py"]}',
            ImplementationResult,
        )
        assert isinstance(result, ImplementationResult)
        assert result.summary == "added auth"
        assert result.changed_files == ["a.py"]

    def test_fallback_infers_pass(self):
        result = parse_llm_response("All tests passed, no issues found")
        assert isinstance(result, dict)
        assert result["status"] == "pass"

    def test_fallback_infers_fail(self):
        result = parse_llm_response("Build failed with 3 errors")
        assert isinstance(result, dict)
        assert result["status"] == "fail"

    def test_fallback_with_model(self):
        result = parse_llm_response("did some stuff", ImplementationResult)
        assert isinstance(result, ImplementationResult)
        assert result.summary  # should have some text

    def test_json_with_preamble(self):
        result = parse_llm_response('Here is the result:\n{"status": "pass"}')
        assert result == {"status": "pass"}

    def test_json_in_code_fence(self):
        result = parse_llm_response('```json\n{"status": "fail"}\n```')
        assert result == {"status": "fail"}


# -- stream filters --

class TestCodexStreamFilter:
    def test_codex_section_shown(self):
        state: dict = {}
        assert _codex_stream_filter("codex", state) is None
        result = _codex_stream_filter("  some output  ", state)
        assert result == "  [codex] some output\n"

    def test_user_section_hidden(self):
        state: dict = {}
        _codex_stream_filter("user", state)
        assert _codex_stream_filter("user input", state) is None

    def test_header_hidden(self):
        state: dict = {}
        assert _codex_stream_filter("some header", state) is None

    def test_separator_hidden(self):
        state: dict = {}
        assert _codex_stream_filter("--------", state) is None

    def test_mcp_startup_hidden(self):
        state: dict = {}
        assert _codex_stream_filter("mcp startup: something", state) is None

    def test_empty_line_in_codex_section(self):
        state: dict = {}
        _codex_stream_filter("codex", state)
        assert _codex_stream_filter("   ", state) is None


class TestClaudeStreamFilter:
    def test_nonempty_shown(self):
        state: dict = {}
        assert _claude_stream_filter("hello", state) == "  [claude] hello\n"

    def test_empty_hidden(self):
        state: dict = {}
        assert _claude_stream_filter("   ", state) is None
