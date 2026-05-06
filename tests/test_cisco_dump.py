from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest

from network_scripts import cisco_dump


class FakeSerial:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def read(self, _size: int = 1) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        return b""

    def close(self) -> None:
        self.closed = True


def test_default_config_dump_output_filename_uses_timestamp() -> None:
    output = cisco_dump.default_output_path(datetime(2026, 5, 5, 12, 34, 56, tzinfo=timezone.utc))

    assert output == Path("config-dump-20260505-123456.txt")


def test_credentials_prefer_cli_options_then_environment_then_prompt() -> None:
    prompts: list[tuple[str, bool]] = []

    def prompt(label: str, hide_input: bool) -> str:
        prompts.append((label, hide_input))
        return "prompted"

    credentials = cisco_dump.resolve_credentials(
        username="cli-user",
        password=None,
        enable_secret="cli-enable",
        env={"IOS_USER": "env-user", "IOS_PASS": "env-pass", "IOS_ENABLE": "env-enable"},
        prompt=prompt,
    )

    assert credentials == cisco_dump.Credentials(
        username="cli-user",
        password="env-pass",
        enable_secret="cli-enable",
    )
    assert prompts == []


def test_credentials_do_not_prompt_for_enable_secret_when_enable_is_disabled() -> None:
    prompts: list[tuple[str, bool]] = []

    def prompt(label: str, hide_input: bool) -> str:
        prompts.append((label, hide_input))
        return "prompted"

    credentials = cisco_dump.resolve_credentials(
        username="admin",
        password="pass",
        env={},
        prompt=prompt,
        require_enable_secret=False,
    )

    assert credentials == cisco_dump.Credentials("admin", "pass", "")
    assert prompts == []


def test_credentials_prompt_for_missing_values() -> None:
    answers = iter(["prompt-user", "prompt-pass", "prompt-enable"])
    prompts: list[tuple[str, bool]] = []

    def prompt(label: str, hide_input: bool) -> str:
        prompts.append((label, hide_input))
        return next(answers)

    credentials = cisco_dump.resolve_credentials(env={}, prompt=prompt)

    assert credentials == cisco_dump.Credentials(
        username="prompt-user",
        password="prompt-pass",
        enable_secret="prompt-enable",
    )
    assert prompts == [("Username", False), ("Password", True), ("Enable secret (blank if none)", True)]


def test_capture_config_dump_logs_in_enters_enable_and_runs_config_commands(tmp_path: Path) -> None:
    fake = FakeSerial(
        [
            b"Username:",
            b"Password:",
            b"\r\nSwitch>",
            b"Password:",
            b"\r\nSwitch#",
            b"\r\nSwitch#",
            b"\r\nCisco IOS XE Software\r\nSwitch#",
            b"\r\nInterface IP-Address OK? Method Status Protocol\r\nSwitch#",
            b"\r\nBuilding configuration...\r\nend\r\nSwitch#",
        ]
    )
    stdout = StringIO()
    stderr = StringIO()

    output_path = cisco_dump.capture_config_dump(
        serial_path="/dev/ttyUSB0",
        baud=9600,
        credentials=cisco_dump.Credentials(
            username="admin",
            password="login-pass",
            enable_secret="enable-pass",
        ),
        output_path=tmp_path / "dump.txt",
        login_timeout=1,
        command_timeout=1,
        debug=True,
        serial_factory=lambda path, baud: fake,
        stdout=stdout,
        stderr=stderr,
    )

    assert output_path == tmp_path / "dump.txt"
    assert fake.writes == [
        b"\r",
        b"admin\r",
        b"login-pass\r",
        b"enable\r",
        b"enable-pass\r",
        b"terminal length 0\r",
        b"show version\r",
        b"show ip interface brief\r",
        b"show running-config\r",
        b"exit\r",
    ]
    assert "show running-config" in stderr.getvalue()
    assert "login-pass" not in stderr.getvalue()
    assert "enable-pass" not in stderr.getvalue()
    assert "<redacted>" in stderr.getvalue()
    assert "Cisco IOS XE Software" in output_path.read_text()
    assert "Building configuration" in output_path.read_text()
    assert "wrote Config Dump" in stdout.getvalue()
    assert fake.closed is True


def test_capture_diagnostic_dump_skips_enable_and_running_config(tmp_path: Path) -> None:
    fake = FakeSerial(
        [
            b"Username:",
            b"Password:",
            b"\r\nSwitch>",
            b"\r\nSwitch>",
            b"\r\nCisco IOS XE Software\r\nSwitch>",
            b"\r\nInterface IP-Address OK? Method Status Protocol\r\nSwitch>",
        ]
    )
    stdout = StringIO()

    output_path = cisco_dump.capture_config_dump(
        serial_path="/dev/ttyUSB0",
        baud=9600,
        credentials=cisco_dump.Credentials(
            username="admin",
            password="login-pass",
            enable_secret="",
        ),
        output_path=tmp_path / "diagnostic.txt",
        login_timeout=1,
        command_timeout=1,
        enable=False,
        serial_factory=lambda path, baud: fake,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert output_path == tmp_path / "diagnostic.txt"
    assert fake.writes == [
        b"\r",
        b"admin\r",
        b"login-pass\r",
        b"terminal length 0\r",
        b"show version\r",
        b"show ip interface brief\r",
        b"exit\r",
    ]
    assert "Building configuration" not in output_path.read_text()
    assert "wrote Diagnostic Dump" in stdout.getvalue()
    assert "running configuration was not captured" in stdout.getvalue()
    assert fake.closed is True


def test_capture_config_dump_times_out_when_prompt_never_arrives(tmp_path: Path) -> None:
    current_time = [0.0]
    fake = FakeSerial([])

    def advance(seconds: float) -> None:
        current_time[0] += seconds

    with pytest.raises(cisco_dump.CiscoDumpError, match="timed out"):
        cisco_dump.capture_config_dump(
            serial_path="/dev/ttyUSB0",
            baud=9600,
            credentials=cisco_dump.Credentials("admin", "pass", "enable"),
            output_path=tmp_path / "dump.txt",
            login_timeout=0.03,
            command_timeout=1,
            serial_factory=lambda path, baud: fake,
            stdout=StringIO(),
            stderr=StringIO(),
            clock=lambda: current_time[0],
            sleep=advance,
        )

    assert fake.closed is True
