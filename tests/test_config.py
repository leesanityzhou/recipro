from __future__ import annotations

from pathlib import Path

import pytest

from recipro.config import AppConfig, _parse_scalar, load_settings, save_setting


# -- _parse_scalar --

class TestParseScalar:
    def test_true(self):
        assert _parse_scalar("true") is True
        assert _parse_scalar("True") is True
        assert _parse_scalar("TRUE") is True

    def test_false(self):
        assert _parse_scalar("false") is False

    def test_none(self):
        assert _parse_scalar("null") is None
        assert _parse_scalar("none") is None

    def test_int(self):
        assert _parse_scalar("42") == 42
        assert _parse_scalar("-1") == -1

    def test_float(self):
        assert _parse_scalar("3.14") == 3.14

    def test_string(self):
        assert _parse_scalar("hello") == "hello"

    def test_empty(self):
        assert _parse_scalar("") == ""

    def test_whitespace_stripped(self):
        assert _parse_scalar("  true  ") is True
        assert _parse_scalar("  42  ") == 42


# -- load_settings / save_setting --

class TestSettings:
    def test_load_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("recipro.config.DATA_DIR", tmp_path)
        settings = load_settings()
        assert settings["max_improvements"] == 1
        assert settings["require_clean_worktree"] is True
        assert settings["add_tests"] is True

    def test_load_from_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("recipro.config.DATA_DIR", tmp_path)
        config_file = tmp_path / "config.yaml"
        config_file.write_text("max_improvements: 5\nadd_tests: false\n")
        settings = load_settings()
        assert settings["max_improvements"] == 5
        assert settings["add_tests"] is False
        # defaults still present
        assert settings["require_clean_worktree"] is True

    def test_load_skips_comments_and_blanks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("recipro.config.DATA_DIR", tmp_path)
        config_file = tmp_path / "config.yaml"
        config_file.write_text("# comment\n\nmax_improvements: 3\n")
        settings = load_settings()
        assert settings["max_improvements"] == 3

    def test_save_creates_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("recipro.config.DATA_DIR", tmp_path)
        config_file = tmp_path / "config.yaml"
        config_file.write_text("max_improvements: 1\n")
        save_setting("add_tests", False)
        text = config_file.read_text()
        assert "add_tests: false" in text
        assert "max_improvements: 1" in text

    def test_save_updates_existing_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("recipro.config.DATA_DIR", tmp_path)
        config_file = tmp_path / "config.yaml"
        config_file.write_text("max_improvements: 1\n")
        save_setting("max_improvements", 10)
        text = config_file.read_text()
        assert "max_improvements: 10" in text
        assert "max_improvements: 1\n" not in text

    def test_save_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("recipro.config.DATA_DIR", tmp_path)
        save_setting("verbose", True)
        text = (tmp_path / "config.yaml").read_text()
        assert "verbose: true" in text


# -- AppConfig --

class TestAppConfig:
    def test_defaults(self):
        config = AppConfig(
            repo_path=Path("/tmp/repo"),
            focus=None,
            max_improvements=1,
            planner_model=None,
            critic_backend="codex",
            critic_model=None,
            builder_backend="claude",
            builder_model=None,
        )
        assert config.add_tests is True
        assert config.dry_run is False
        assert config.auto_merge is False

    def test_with_overrides(self):
        config = AppConfig(
            repo_path=Path("/tmp/repo"),
            focus=None,
            max_improvements=1,
            planner_model=None,
            critic_backend="codex",
            critic_model=None,
            builder_backend="claude",
            builder_model=None,
        )
        updated = config.with_overrides(add_tests=False, max_improvements=5)
        assert updated.add_tests is False
        assert updated.max_improvements == 5
        # original unchanged
        assert config.add_tests is True
