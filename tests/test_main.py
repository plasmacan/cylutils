import runpy
import sys
from unittest.mock import MagicMock, patch


def test_main_module_executes_cli():
    """Covers cylutils/__main__.py: verifies cli() is called when the package is run as __main__."""
    mock_cli = MagicMock()
    with patch("cylutils.cli.cli", mock_cli):
        runpy.run_module("cylutils", run_name="__main__", alter_sys=False)
    mock_cli.assert_called_once_with()
