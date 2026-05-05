from typer.testing import CliRunner

from network_scripts.cli import app


runner = CliRunner()


def test_top_level_help_lists_command_groups() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "serial" in result.output
    assert "cisco" in result.output


def test_serial_help_is_available() -> None:
    result = runner.invoke(app, ["serial", "--help"])

    assert result.exit_code == 0
    assert "Serial Device" in result.output


def test_cisco_help_is_available_with_placeholder() -> None:
    result = runner.invoke(app, ["cisco", "--help"])

    assert result.exit_code == 0
    assert "Cisco Device" in result.output
