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


def test_resolve_serial_device_prefers_explicit_value() -> None:
    resolved = serial_devices.resolve_serial_device(
        explicit_path="/dev/cu.explicit",
        path_exists=lambda _path: False,
    )

    assert resolved == "/dev/cu.explicit"


def test_resolve_serial_device_fails_when_latest_has_not_been_recorded(tmp_path: Path) -> None:
    with pytest.raises(serial_devices.SerialDeviceResolutionError) as exc_info:
        serial_devices.resolve_serial_device(state_dir=tmp_path / ".network-scripts")

    assert "No Latest Serial Device has been recorded" in str(exc_info.value)
    assert "uv run network-scripts serial watch" in str(exc_info.value)
    assert "--serial" in str(exc_info.value)


def test_resolve_serial_device_uses_latest_recorded_device(tmp_path: Path) -> None:
    state_dir = tmp_path / ".network-scripts"
    serial_path = tmp_path / "ttyUSB0"
    serial_path.write_text("")
    serial_devices.write_latest_serial_device(str(serial_path), state_dir=state_dir)

    resolved = serial_devices.resolve_serial_device(state_dir=state_dir)

    assert resolved == str(serial_path)


def test_resolve_serial_device_fails_when_latest_recorded_device_is_stale(tmp_path: Path) -> None:
    state_dir = tmp_path / ".network-scripts"
    stale_path = tmp_path / "ttyUSB0"
    serial_devices.write_latest_serial_device(str(stale_path), state_dir=state_dir)

    with pytest.raises(serial_devices.SerialDeviceResolutionError) as exc_info:
        serial_devices.resolve_serial_device(state_dir=state_dir)

    assert f"Latest Serial Device {stale_path} no longer exists" in str(exc_info.value)
    assert "uv run network-scripts serial watch" in str(exc_info.value)
    assert "--serial" in str(exc_info.value)


def test_resolve_serial_device_does_not_auto_pick_another_device(tmp_path: Path) -> None:
    state_dir = tmp_path / ".network-scripts"
    stale_path = tmp_path / "ttyUSB0"
    other_path = tmp_path / "ttyUSB1"
    other_path.write_text("")
    serial_devices.write_latest_serial_device(str(stale_path), state_dir=state_dir)

    with pytest.raises(serial_devices.SerialDeviceResolutionError) as exc_info:
        serial_devices.resolve_serial_device(state_dir=state_dir)

    assert str(stale_path) in str(exc_info.value)
    assert str(other_path) not in str(exc_info.value)


def test_cisco_dump_accepts_explicit_serial_device() -> None:
    result = runner.invoke(app, ["cisco", "dump", "--serial", "/dev/cu.explicit"])

    assert result.exit_code == 1
    assert "Resolved Serial Device: /dev/cu.explicit" in result.output
    assert "Cisco Device dump capture is not implemented yet" in result.output


def test_cisco_dump_uses_latest_serial_device() -> None:
    with runner.isolated_filesystem():
        Path("ttyUSB0").write_text("")
        serial_devices.write_latest_serial_device("ttyUSB0")

        result = runner.invoke(app, ["cisco", "dump"])

        assert result.exit_code == 1
        assert "Resolved Serial Device: ttyUSB0" in result.output
        assert "Cisco Device dump capture is not implemented yet" in result.output


def test_cisco_dump_fails_clearly_when_latest_serial_device_is_missing() -> None:
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["cisco", "dump"])

        assert result.exit_code == 1
        assert "No Latest Serial Device has been recorded" in result.output
        assert "uv run network-scripts serial watch" in result.output
        assert "--serial" in result.output


def test_cisco_dump_fails_clearly_when_latest_serial_device_is_stale() -> None:
    with runner.isolated_filesystem():
        serial_devices.write_latest_serial_device("ttyUSB0")

        result = runner.invoke(app, ["cisco", "dump"])

        assert result.exit_code == 1
        assert "Latest Serial Device ttyUSB0 no longer exists" in result.output
        assert "uv run network-scripts serial watch" in result.output
        assert "--serial" in result.output
