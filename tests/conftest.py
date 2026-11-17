import dataclasses

import pytest

from cylutils.cli import cli


@dataclasses.dataclass
class CliResult:
    exit_code: int
    output: str
    stderr: str


@pytest.fixture
def run_cli(capsys):
    """Run the cylutils CLI in-process; return its exit code and captured stdout/stderr."""

    def run(args: list[str]) -> CliResult:
        capsys.readouterr()  # drop anything printed before this call
        try:
            cli(args)
            exit_code = 0
        except SystemExit as exc:
            exit_code = 0 if exc.code is None else exc.code
        out, err = capsys.readouterr()
        return CliResult(exit_code, out, err)

    return run
