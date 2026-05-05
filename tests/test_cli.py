import sys
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cylutils.cli import _ask, cli
from cylutils.features import ADDONS, JINJA2, SIMPLE_STORE


# ---------------------------------------------------------------------------
# _ask helper
# ---------------------------------------------------------------------------


class TestAsk:
    def test_returns_provided_value_without_calling_fn(self):
        called = []
        result = _ask("already_set", lambda: called.append(True) or "from_prompt")
        assert result == "already_set"
        assert called == []

    def test_calls_question_fn_when_value_is_none(self):
        result = _ask(None, lambda: "from_prompt")
        assert result == "from_prompt"

    def test_exits_zero_when_question_fn_returns_none(self):
        with pytest.raises(SystemExit) as exc_info:
            _ask(None, lambda: None)
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# start-project command
# ---------------------------------------------------------------------------


def _invoke(args, confirm_returns=False, **runner_kwargs):
    """Invoke the CLI, mocking scaffold and questionary confirm prompts.

    ``confirm_returns`` is returned by any questionary.confirm().ask() call,
    covering the add_g / add_sessions prompts when the flags are omitted.
    """
    runner = CliRunner(**runner_kwargs)
    with patch("cylutils.cli.scaffold") as mock_scaffold, patch(
        "questionary.confirm"
    ) as mock_confirm:
        mock_confirm.return_value.ask.return_value = confirm_returns
        result = runner.invoke(cli, args)
    return result, mock_scaffold


class TestStartProjectCommand:
    def test_no_features_calls_scaffold_with_empty_list(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            ["start-project", "proj", "myapp", "--store-type", "none", "--template-engine", "none"]
        )
        assert result.exit_code == 0
        mock_scaffold.assert_called_once_with("proj", "myapp", [])

    def test_simple_store_feature_selected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            ["start-project", "proj", "myapp", "--store-type", "simple_store", "--template-engine", "none"]
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert SIMPLE_STORE in features

    def test_jinja2_feature_selected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            ["start-project", "proj", "myapp", "--store-type", "none", "--template-engine", "jinja2"]
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert JINJA2 in features

    def test_add_g_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            [
                "start-project", "proj", "myapp",
                "--store-type", "none", "--template-engine", "none",
                "--add-g",
            ]
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert ADDONS["g"] in features

    def test_add_sessions_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            [
                "start-project", "proj", "myapp",
                "--store-type", "none", "--template-engine", "none",
                "--add-sessions",
            ]
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert ADDONS["sessions"] in features

    def test_all_features_flags(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            [
                "start-project", "proj", "myapp",
                "--store-type", "simple_store", "--template-engine", "jinja2",
                "--add-g", "--add-sessions",
            ]
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert SIMPLE_STORE in features
        assert JINJA2 in features
        assert ADDONS["g"] in features
        assert ADDONS["sessions"] in features

    def test_existing_directory_exits_with_code_1(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "existing").mkdir()
        result, mock_scaffold = _invoke(
            ["start-project", "existing", "myapp", "--store-type", "none", "--template-engine", "none"],
        )
        assert result.exit_code == 1
        mock_scaffold.assert_not_called()

    def test_done_message_printed_on_success(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, _ = _invoke(
            ["start-project", "proj", "myapp", "--store-type", "none", "--template-engine", "none"]
        )
        assert "Done" in result.output

    def test_project_name_prompted_when_not_provided(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("cylutils.cli.scaffold"), \
             patch("questionary.text") as mock_text, \
             patch("questionary.select") as mock_select, \
             patch("questionary.confirm") as mock_confirm:
            mock_text.return_value.ask.return_value = "prompted-proj"
            mock_select.return_value.ask.return_value = "none"
            mock_confirm.return_value.ask.return_value = False
            result = runner.invoke(cli, ["start-project"])
        assert result.exit_code == 0

    def test_cancel_project_name_prompt_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        with patch("questionary.text") as mock_text:
            mock_text.return_value.ask.return_value = None
            result = runner.invoke(cli, ["start-project"])
        assert result.exit_code == 0
