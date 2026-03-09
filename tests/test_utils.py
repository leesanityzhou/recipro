from __future__ import annotations

import pytest

from recipro.utils import (
    CommandError,
    dedupe_strings,
    extract_json_value,
    slugify,
    _codex_stream_filter,
    _claude_stream_filter,
)


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
