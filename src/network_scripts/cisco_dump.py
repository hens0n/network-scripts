from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
import os
from pathlib import Path
import re
import sys
import time
from typing import Callable, Mapping, Optional, Protocol, TextIO


class SerialStream(Protocol):
    def write(self, data: bytes) -> Optional[int]: ...

    def read(self, size: int = 1) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    enable_secret: str


class CiscoDumpError(RuntimeError):
    pass


Prompt = Callable[[str, bool], str]
SerialFactory = Callable[[str, int], SerialStream]
Clock = Callable[[], float]
Sleep = Callable[[float], None]


def default_output_path(now: Optional[datetime] = None, *, enable: bool = True) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    prefix = "config-dump" if enable else "diagnostic-dump"
    return Path(f"{prefix}-{timestamp}.txt")


def resolve_credentials(
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    enable_secret: Optional[str] = None,
    env: Mapping[str, str] = os.environ,
    prompt: Prompt,
    require_enable_secret: bool = True,
) -> Credentials:
    resolved_username = username if username is not None else env.get("IOS_USER")
    while not resolved_username:
        resolved_username = prompt("Username", False).strip()

    resolved_password = password if password is not None else env.get("IOS_PASS")
    if resolved_password is None:
        resolved_password = prompt("Password", True)

    resolved_enable = enable_secret if enable_secret is not None else env.get("IOS_ENABLE")
    if resolved_enable is None and require_enable_secret:
        resolved_enable = prompt("Enable secret (blank if none)", True)
    if resolved_enable is None:
        resolved_enable = ""

    return Credentials(
        username=resolved_username,
        password=_strip_control_characters(resolved_password),
        enable_secret=_strip_control_characters(resolved_enable),
    )


def open_pyserial(path: str, baud: int) -> SerialStream:
    serial_module = importlib.import_module("serial")
    return serial_module.Serial(  # type: ignore[no-any-return]
        port=path,
        baudrate=baud,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=0,
        write_timeout=1,
    )


def capture_config_dump(
    *,
    serial_path: str,
    baud: int,
    credentials: Credentials,
    output_path: Path,
    login_timeout: float = 60.0,
    command_timeout: float = 120.0,
    enable: bool = True,
    debug: bool = False,
    serial_factory: SerialFactory = open_pyserial,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    clock: Clock = time.monotonic,
    sleep: Sleep = time.sleep,
) -> Path:
    stream = serial_factory(serial_path, baud)
    session = _CiscoSession(
        stream=stream,
        output_path=output_path,
        credentials=credentials,
        debug=debug,
        stdout=stdout,
        stderr=stderr,
        clock=clock,
        sleep=sleep,
    )
    try:
        session.login(timeout=login_timeout, enable=enable)
        commands = [
            "terminal length 0",
            "show version",
            "show ip interface brief",
        ]
        if enable:
            commands.append("show running-config")
        for command in commands:
            session.run_command(command, timeout=command_timeout)
        session.send("exit", secret=False)
    finally:
        session.close()

    if enable:
        print(f"\n--- wrote Config Dump to {output_path} ---", file=stdout)
    else:
        print(
            f"\n--- wrote Diagnostic Dump to {output_path}; running configuration was not captured ---",
            file=stdout,
        )
    return output_path


class _CiscoSession:
    def __init__(
        self,
        *,
        stream: SerialStream,
        output_path: Path,
        credentials: Credentials,
        debug: bool,
        stdout: TextIO,
        stderr: TextIO,
        clock: Clock,
        sleep: Sleep,
    ) -> None:
        self.stream = stream
        self.output_path = output_path
        self.credentials = credentials
        self.debug = debug
        self.stdout = stdout
        self.stderr = stderr
        self.clock = clock
        self.sleep = sleep
        self.buffer = ""
        self.transcript = output_path.open("w", encoding="utf-8", errors="replace")

    def close(self) -> None:
        try:
            self.transcript.close()
        finally:
            self.stream.close()

    def login(self, *, timeout: float, enable: bool) -> None:
        username_sends = 0
        password_sends = 0
        enable_password_sends = 0
        enabling = False
        self.send("", secret=False)
        deadline = self.clock() + timeout

        while True:
            idx = self.expect(
                [
                    r"Press RETURN",
                    r"authentication failed|% Access denied|% Login invalid|% Authentication failed",
                    r"username:[ \t]*$",
                    r"password:[ \t]*$",
                    r"[\r\n][^\r\n#>]*>[ \t]*$",
                    r"[\r\n][^\r\n#>]*#[ \t]*$",
                ],
                deadline=deadline,
            )
            if idx == 0:
                self.send("", secret=False)
            elif idx == 1:
                raise CiscoDumpError("login rejected by Cisco Device")
            elif idx == 2:
                username_sends += 1
                if username_sends > 3:
                    raise CiscoDumpError("too many username prompts from Cisco Device")
                enabling = False
                self.send(self.credentials.username, secret=False)
            elif idx == 3:
                if enabling:
                    enable_password_sends += 1
                    if enable_password_sends > 2:
                        raise CiscoDumpError("too many enable secret prompts from Cisco Device")
                    self.send(self.credentials.enable_secret, secret=True)
                else:
                    password_sends += 1
                    if password_sends > 2:
                        raise CiscoDumpError("too many password prompts from Cisco Device")
                    self.send(self.credentials.password, secret=True)
            elif idx == 4:
                if not enable:
                    return
                enabling = True
                self.send("enable", secret=False)
            elif idx == 5:
                return

    def run_command(self, command: str, *, timeout: float) -> None:
        self.send(command, secret=False)
        deadline = self.clock() + timeout
        self.expect(
            [
                r"[\r\n][^\r\n#>]*[#>][ \t]*$",
                r"[#>][ \t]*$",
            ],
            deadline=deadline,
        )

    def send(self, command: str, *, secret: bool) -> None:
        wire_text = f"{command}\r"
        if self.debug:
            visible = "<redacted>" if secret else command
            print(f"[send] {visible!r}", file=self.stderr, flush=True)
        payload = wire_text.encode("utf-8", "replace")
        written = self.stream.write(payload)
        if written is not None and written != len(payload):
            raise CiscoDumpError("serial write was incomplete")

    def expect(self, patterns: list[str], *, deadline: float) -> int:
        compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        if self.debug:
            print(f"[expect] waiting for {patterns}", file=self.stderr, flush=True)
        while True:
            for index, pattern in enumerate(compiled):
                match = pattern.search(self.buffer)
                if match:
                    self.buffer = self.buffer[match.end() :]
                    if self.debug:
                        print(f"[match] #{index}: {match.group(0)!r}", file=self.stderr, flush=True)
                    return index

            chunk = self.stream.read(4096)
            if chunk:
                text = chunk.decode("utf-8", "replace")
                self.stdout.write(text)
                self.stdout.flush()
                self.transcript.write(text)
                self.transcript.flush()
                self.buffer += text
                continue

            if self.clock() >= deadline:
                raise CiscoDumpError(
                    "timed out waiting for Cisco Device; last transcript text: "
                    f"{self.buffer[-200:]!r}"
                )
            self.sleep(0.01)


def _strip_control_characters(value: str) -> str:
    return "".join(character for character in value if character >= " " or character == "\t")
