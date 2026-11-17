import sys
from unittest.mock import patch

import pytest

from cylutils.cli import _ask, _existing_path, build_parser, cli
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
# Parser
# ---------------------------------------------------------------------------


class TestParser:
    def test_no_command_prints_help_and_exits_2(self, run_cli):
        result = run_cli([])
        assert result.exit_code == 2
        assert "start-project" in result.stderr
        assert "openapi" in result.stderr

    def test_openapi_without_subcommand_prints_its_help(self, run_cli):
        result = run_cli(["openapi"])
        assert result.exit_code == 2
        for name in ("export", "scaffold", "ui"):
            assert name in result.stderr

    def test_help_exits_zero(self, run_cli):
        result = run_cli(["start-project", "--help"])
        assert result.exit_code == 0
        assert "--store-type" in result.output
        assert "asked for interactively" in result.output

    def test_command_help_comes_from_handler_docstring(self, run_cli):
        result = run_cli(["openapi", "export", "--help"])
        assert "Export a Cylinder app's routes" in result.output
        assert "(default: Cylinder App)" in result.output

    def test_invalid_choice_is_a_usage_error(self, run_cli):
        result = run_cli(["start-project", "p", "a", "--store-type", "bogus"])
        assert result.exit_code == 2
        assert "invalid choice: 'bogus'" in result.stderr

    def test_missing_path_is_a_usage_error(self, run_cli, tmp_path):
        result = run_cli(["openapi", "export", str(tmp_path / "nope")])
        assert result.exit_code == 2
        assert "does not exist" in result.stderr

    def test_flags_default_to_none_so_omitted_means_ask(self):
        args = build_parser().parse_args(["start-project"])
        assert (args.add_g, args.add_sessions, args.add_http) == (None, None, None)
        args = build_parser().parse_args(["start-project", "--add-g"])
        assert args.add_g is True

    def test_reads_sys_argv_by_default(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["cylutils", "openapi"])
        with pytest.raises(SystemExit) as exc_info:
            cli()
        assert exc_info.value.code == 2

    def test_existing_path_returns_value(self, tmp_path):
        assert _existing_path(str(tmp_path)) == str(tmp_path)

    def test_openapi_ui_stub_accepts_its_arguments(self, run_cli, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text("openapi: 3.0.3\n", encoding="utf-8")
        result = run_cli(["openapi", "ui", str(spec), str(tmp_path / "ui")])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# start-project command
# ---------------------------------------------------------------------------


def _invoke(run_cli, args, confirm_returns=False):
    """Invoke the CLI, mocking scaffold and questionary confirm prompts.

    ``confirm_returns`` is returned by any questionary.confirm().ask() call,
    covering the add_g / add_sessions / add_http prompts when the flags are omitted.
    """
    with patch("cylutils.cli.scaffold") as mock_scaffold, patch(
        "questionary.confirm"
    ) as mock_confirm:
        mock_confirm.return_value.ask.return_value = confirm_returns
        result = run_cli(args)
    return result, mock_scaffold


class TestStartProjectCommand:
    def test_no_features_calls_scaffold_with_empty_list(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            run_cli,
            ["start-project", "proj", "myapp", "--store-type", "none", "--template-engine", "none"],
        )
        assert result.exit_code == 0
        mock_scaffold.assert_called_once_with("proj", "myapp", [])

    def test_simple_store_feature_selected(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            run_cli,
            ["start-project", "proj", "myapp", "--store-type", "simple_store", "--template-engine", "none"],
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert SIMPLE_STORE in features

    def test_jinja2_feature_selected(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            run_cli,
            ["start-project", "proj", "myapp", "--store-type", "none", "--template-engine", "jinja2"],
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert JINJA2 in features

    def test_add_g_flag(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            run_cli,
            [
                "start-project", "proj", "myapp",
                "--store-type", "none", "--template-engine", "none",
                "--add-g",
            ],
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert ADDONS["g"] in features

    def test_add_sessions_flag(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            run_cli,
            [
                "start-project", "proj", "myapp",
                "--store-type", "none", "--template-engine", "none",
                "--add-sessions",
            ],
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert ADDONS["sessions"] in features

    def test_add_http_flag(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            run_cli,
            [
                "start-project", "proj", "myapp",
                "--store-type", "none", "--template-engine", "none",
                "--add-http",
            ],
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert ADDONS["http"] in features

    def test_http_omitted_when_prompt_declined(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            run_cli,
            ["start-project", "proj", "myapp", "--store-type", "none", "--template-engine", "none"],
            confirm_returns=False,
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert ADDONS["http"] not in features

    def test_all_features_flags(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, mock_scaffold = _invoke(
            run_cli,
            [
                "start-project", "proj", "myapp",
                "--store-type", "simple_store", "--template-engine", "jinja2",
                "--add-g", "--add-sessions", "--add-http",
            ],
        )
        assert result.exit_code == 0
        _, _, features = mock_scaffold.call_args[0]
        assert SIMPLE_STORE in features
        assert JINJA2 in features
        assert ADDONS["g"] in features
        assert ADDONS["sessions"] in features
        assert ADDONS["http"] in features

    def test_existing_directory_exits_with_code_1(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "existing").mkdir()
        result, mock_scaffold = _invoke(
            run_cli,
            ["start-project", "existing", "myapp", "--store-type", "none", "--template-engine", "none"],
        )
        assert result.exit_code == 1
        assert "already exists" in result.stderr
        mock_scaffold.assert_not_called()

    def test_done_message_printed_on_success(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result, _ = _invoke(
            run_cli,
            ["start-project", "proj", "myapp", "--store-type", "none", "--template-engine", "none"],
        )
        assert "Done" in result.output

    def test_project_name_prompted_when_not_provided(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("cylutils.cli.scaffold") as mock_scaffold, \
             patch("questionary.text") as mock_text, \
             patch("questionary.select") as mock_select, \
             patch("questionary.confirm") as mock_confirm:
            mock_text.return_value.ask.return_value = "prompted-proj"
            mock_select.return_value.ask.return_value = "none"
            mock_confirm.return_value.ask.return_value = False
            result = run_cli(["start-project"])
        assert result.exit_code == 0
        mock_scaffold.assert_called_once_with("prompted-proj", "prompted-proj", [])

    def test_cancel_project_name_prompt_exits_zero(self, run_cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("questionary.text") as mock_text:
            mock_text.return_value.ask.return_value = None
            result = run_cli(["start-project"])
        assert result.exit_code == 0
