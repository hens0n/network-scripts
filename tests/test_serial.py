from pathlib import Path

import pytest
from typer.testing import CliRunner

from network_scripts import serial_devices
from network_scripts.cli import app


runner = CliRunner()


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")


def test_macos_serial_device_discovery_filters_built_ins(tmp_path: Path) -> None:
    touch(tmp_path / "cu.usbserial-123")
    touch(tmp_path / "cu.Bluetooth-Incoming-Port")
    touch(tmp_path / "cu.debug-console")
    touch(tmp_path / "ttyUSB0")

    devices = serial_devices.discover_serial_devices(tmp_path, platform="darwin")

    assert devices == [str(tmp_path / "cu.usbserial-123")]


def test_linux_serial_device_discovery_includes_usb_and_acm(tmp_path: Path) -> None:
    touch(tmp_path / "ttyUSB0")
    touch(tmp_path / "ttyACM0")
    touch(tmp_path / "cu.usbserial-123")

    devices = serial_devices.discover_serial_devices(tmp_path, platform="linux")

    assert devices == [str(tmp_path / "ttyACM0"), str(tmp_path / "ttyUSB0")]


def test_latest_serial_device_state_round_trips(tmp_path: Path) -> None:
    state_dir = tmp_path / ".network-scripts"

    serial_devices.write_latest_serial_device(
        "/dev/cu.usbserial-123",
        state_dir=state_dir,
        observed_at="2026-05-05T12:00:00Z",
    )

    latest = serial_devices.read_latest_serial_device(state_dir=state_dir)
    assert latest == serial_devices.LatestSerialDevice(
        path="/dev/cu.usbserial-123",
        observed_at="2026-05-05T12:00:00Z",
    )


def test_watch_returns_new_serial_device_after_baseline_snapshot() -> None:
    snapshots = iter(
        [
            ["/dev/cu.existing"],
            ["/dev/cu.existing"],
            ["/dev/cu.existing", "/dev/cu.usbserial-123"],
        ]
    )
    current_time = [0.0]

    def advance(seconds: float) -> None:
        current_time[0] += seconds

    detected = serial_devices.wait_for_new_serial_device(
        discover_devices=lambda: next(snapshots),
        timeout=1.0,
        poll_interval=0.1,
        sleep=advance,
        clock=lambda: current_time[0],
    )

    assert detected == "/dev/cu.usbserial-123"


def test_watch_times_out_when_no_new_serial_device_appears() -> None:
    current_time = [0.0]

    def advance(seconds: float) -> None:
        current_time[0] += seconds

    with pytest.raises(serial_devices.SerialDeviceWatchTimeout):
        serial_devices.wait_for_new_serial_device(
            discover_devices=lambda: ["/dev/cu.existing"],
            timeout=0.3,
            poll_interval=0.1,
            sleep=advance,
            clock=lambda: current_time[0],
        )


def test_serial_watch_path_only_records_latest_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        serial_devices,
        "wait_for_new_serial_device",
        lambda **_kwargs: "/dev/cu.usbserial-123",
    )

    with runner.isolated_filesystem():
        result = runner.invoke(app, ["serial", "watch", "--path-only"])

        assert result.exit_code == 0
        assert result.output == "/dev/cu.usbserial-123\n"
        assert serial_devices.read_latest_serial_device().path == "/dev/cu.usbserial-123"
