#!/usr/bin/env python3
"""Log into a Cisco IOS/IOS-XE device over serial and dump its running-config.

Driven by dump-cisco-config.sh which sets:
  SERIAL_DEV  serial device path (e.g. /dev/cu.usbserial-1120)
  BAUD        baud rate (default 9600)
  IOS_USER    login username
  IOS_PASS    login password
  IOS_ENABLE  enable secret (may be empty)
  OUT         output transcript path
  DEBUG       set non-empty to enable verbose tracing on stderr
"""

from __future__ import annotations

import os
import re
import select
import sys
import termios
import time

PORT = os.environ["SERIAL_DEV"]
BAUD = int(os.environ.get("BAUD", "9600"))
USER = os.environ["IOS_USER"]
PASS = os.environ.get("IOS_PASS", "")
ENABLE = os.environ.get("IOS_ENABLE", "")
OUT = os.environ.get("OUT", "router-config.txt")
DEBUG = bool(os.environ.get("DEBUG", "").strip())

# Map common bauds to termios constants.
BAUD_MAP = {
    1200: termios.B1200, 2400: termios.B2400, 4800: termios.B4800,
    9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
    57600: termios.B57600, 115200: termios.B115200,
}
if BAUD not in BAUD_MAP:
    sys.exit(f"unsupported baud: {BAUD}")


def dbg(msg: str) -> None:
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr, flush=True)


def open_serial(path: str, baud: int) -> int:
    """Open the serial device and put it in 8N1 raw, no echo, no flow control."""
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs

    # cflag: 8 data, no parity, 1 stop, ignore modem ctrl, enable receiver, no hw flow.
    cflag &= ~(termios.PARENB | termios.CSTOPB | termios.CSIZE | termios.CRTSCTS)
    cflag |= termios.CS8 | termios.CLOCAL | termios.CREAD

    # iflag: no SW flow, no break translation, no CR/NL mangling, no parity check.
    iflag &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
    iflag &= ~(termios.INLCR | termios.IGNCR | termios.ICRNL)
    iflag &= ~(termios.BRKINT | termios.IGNBRK | termios.PARMRK | termios.INPCK | termios.ISTRIP)

    # oflag: no output post-processing.
    oflag &= ~termios.OPOST

    # lflag: no canonical, no echo, no signal generation.
    lflag &= ~(termios.ICANON | termios.ECHO | termios.ECHOE | termios.ECHONL | termios.ISIG | termios.IEXTEN)

    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 0
    ispeed = ospeed = BAUD_MAP[baud]

    termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


class Session:
    def __init__(self, fd: int, transcript_path: str):
        self.fd = fd
        self.buf = ""
        self.transcript = open(transcript_path, "w", encoding="utf-8", errors="replace")

    def close(self) -> None:
        try:
            self.transcript.close()
        finally:
            os.close(self.fd)

    def send(self, data: str) -> None:
        # Always log sends to stderr so we can see what reached the wire
        # without needing DEBUG. Loop until all bytes are written.
        payload = data.encode("utf-8", "replace")
        print(f"[send] {data!r} ({len(payload)}B)", file=sys.stderr, flush=True)
        view = memoryview(payload)
        while view:
            try:
                n = os.write(self.fd, view)
            except BlockingIOError:
                select.select([], [self.fd], [], 1.0)
                continue
            if n <= 0:
                raise OSError("os.write returned 0")
            view = view[n:]
        try:
            termios.tcdrain(self.fd)
        except OSError:
            pass

    def expect(self, patterns: list[str], timeout: float) -> tuple[int, str]:
        """Wait until one of the regex patterns matches the receive buffer.

        Returns (index, matched_text). Index of -1 means timeout.
        """
        compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
        print(f"[expect] waiting for one of: {patterns}", file=sys.stderr, flush=True)
        deadline = time.monotonic() + timeout
        while True:
            for i, pat in enumerate(compiled):
                m = pat.search(self.buf)
                if m:
                    matched = m.group(0)
                    self.buf = self.buf[m.end():]
                    print(f"[match] #{i}: {matched!r}", file=sys.stderr, flush=True)
                    return i, matched

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(f"[timeout] last 200 chars of buf: {self.buf[-200:]!r}", file=sys.stderr, flush=True)
                return -1, ""

            r, _, _ = select.select([self.fd], [], [], min(remaining, 0.5))
            if not r:
                continue
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                continue
            if not chunk:
                continue
            text = chunk.decode("utf-8", "replace")
            sys.stdout.write(text)
            sys.stdout.flush()
            self.transcript.write(text)
            self.transcript.flush()
            self.buf += text


def login(s: Session) -> None:
    user_attempts = 0
    pass_attempts = 0
    s.send("\r")  # one wake-up CR
    while True:
        idx, _ = s.expect([
            r"Press RETURN",
            r"authentication failed|% Access denied|% Login invalid|% Authentication failed",
            r"username:[ \t]*$",
            r"password:[ \t]*$",
            r"[\r\n][^\r\n#>]*>[ \t]*$",
            r"[\r\n][^\r\n#>]*#[ \t]*$",
        ], timeout=60)

        if idx == -1:
            sys.exit("error: never reached enable prompt (see transcript)")
        if idx == 0:
            s.send("\r")
        elif idx == 1:
            sys.exit("error: login rejected by router")
        elif idx == 2:
            user_attempts += 1
            if user_attempts > 3:
                sys.exit("error: too many username re-prompts")
            s.send(f"{USER}\r")
        elif idx == 3:
            pass_attempts += 1
            if pass_attempts > 2:
                sys.exit("error: too many password re-prompts")
            s.send(f"{PASS}\r")
        elif idx == 4:
            s.send("enable\r")
        elif idx == 5:
            return  # at #


def maybe_enable_secret(s: Session) -> None:
    idx, _ = s.expect([
        r"password:[ \t]*$",
        r"[\r\n][^\r\n#>]*#[ \t]*$",
    ], timeout=5)
    if idx == 0:
        s.send(f"{ENABLE}\r")
        s.expect([r"[\r\n][^\r\n#>]*#[ \t]*$"], timeout=10)


def run_command(s: Session, cmd: str, timeout: float = 120) -> None:
    s.send(f"{cmd}\r")
    s.expect([r"#[ \t]*$"], timeout=timeout)


def main() -> int:
    fd = open_serial(PORT, BAUD)
    s = Session(fd, OUT)
    try:
        login(s)
        maybe_enable_secret(s)
        run_command(s, "terminal length 0")
        run_command(s, "show version")
        run_command(s, "show ip interface brief")
        run_command(s, "show running-config")
        s.send("exit\r")
        time.sleep(0.5)
    finally:
        s.close()
    print(f"\n--- wrote transcript to {OUT} ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
