from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Callable, Iterable, Optional

STATE_DIR = Path(".network-scripts")
LATEST_SERIAL_DEVICE_FILE = "latest-serial-device.json"


@dataclass(frozen=True)
class LatestSerialDevice:
    path: str
    observed_at: str


class SerialDeviceWatchTimeout(RuntimeError):
    pass


def discover_serial_devices(
    dev_dir: Path = Path("/dev"),
    *,
    platform: Optional[str] = None,
) -> list[str]:
    platform_name = platform or sys.platform
    if platform_name == "darwin":
        devices = dev_dir.glob("cu.*")
        return sorted(
            str(device)
            for device in devices
            if not _is_macos_builtin_serial_device(device.name)
        )
    if platform_name.startswith("linux"):
        return sorted(
            str(device)
            for pattern in ("ttyUSB*", "ttyACM*")
            for device in dev_dir.glob(pattern)
        )
    return []


def wait_for_new_serial_device(
    *,
    discover_devices: Callable[[], Iterable[str]] = discover_serial_devices,
    timeout: float = 60.0,
    poll_interval: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    baseline = set(discover_devices())
    deadline = clock() + timeout

    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise SerialDeviceWatchTimeout(
                f"No new Serial Device appeared within {timeout:g} seconds."
            )
        sleep(min(poll_interval, remaining))
        current = set(discover_devices())
        added = sorted(current - baseline)
        if added:
            return added[0]


def write_latest_serial_device(
    path: str,
    *,
    state_dir: Path = STATE_DIR,
    observed_at: Optional[str] = None,
) -> LatestSerialDevice:
    latest = LatestSerialDevice(
        path=path,
        observed_at=observed_at or _current_timestamp(),
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    latest_path = state_dir / LATEST_SERIAL_DEVICE_FILE
    latest_path.write_text(
        json.dumps({"path": latest.path, "observed_at": latest.observed_at}, indent=2)
        + "\n"
    )
    return latest


def read_latest_serial_device(
    *,
    state_dir: Path = STATE_DIR,
) -> LatestSerialDevice:
    latest_path = state_dir / LATEST_SERIAL_DEVICE_FILE
    data = json.loads(latest_path.read_text())
    return LatestSerialDevice(path=str(data["path"]), observed_at=str(data["observed_at"]))


def _is_macos_builtin_serial_device(name: str) -> bool:
    return "Bluetooth" in name or name == "cu.debug-console" or "debug-console" in name


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
