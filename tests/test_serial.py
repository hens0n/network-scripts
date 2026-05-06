from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from network_scripts import cisco_dump, serial_devices
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


def test_cisco_dump_accepts_explicit_serial_device(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def capture(**kwargs: Any) -> Path:
        calls.append(kwargs)
        return kwargs["output_path"]

    monkeypatch.setattr(cisco_dump, "capture_config_dump", capture)

    result = runner.invoke(
        app,
        [
            "cisco",
            "dump",
            "--serial",
            "/dev/cu.explicit",
            "--user",
            "admin",
            "--password",
            "pass",
            "--enable",
            "enable",
            "--out",
            "dump.txt",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["serial_path"] == "/dev/cu.explicit"
    assert calls[0]["credentials"] == cisco_dump.Credentials("admin", "pass", "enable")
    assert calls[0]["output_path"] == Path("dump.txt")


def test_cisco_dump_no_enable_captures_diagnostic_dump_without_enable_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def capture(**kwargs: Any) -> Path:
        calls.append(kwargs)
        return kwargs["output_path"]

    monkeypatch.setattr(cisco_dump, "capture_config_dump", capture)

    result = runner.invoke(
        app,
        [
            "cisco",
            "dump",
            "--serial",
            "/dev/cu.explicit",
            "--user",
            "admin",
            "--password",
            "pass",
            "--no-enable",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["enable"] is False
    assert calls[0]["credentials"] == cisco_dump.Credentials("admin", "pass", "")
    assert calls[0]["output_path"].name.startswith("diagnostic-dump-")


def test_cisco_dump_uses_latest_serial_device(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def capture(**kwargs: Any) -> Path:
        calls.append(kwargs)
        return kwargs["output_path"]

    monkeypatch.setenv("IOS_USER", "admin")
    monkeypatch.setenv("IOS_PASS", "pass")
    monkeypatch.setenv("IOS_ENABLE", "enable")
    monkeypatch.setattr(cisco_dump, "capture_config_dump", capture)

    with runner.isolated_filesystem():
        Path("ttyUSB0").write_text("")
        serial_devices.write_latest_serial_device("ttyUSB0")

        result = runner.invoke(app, ["cisco", "dump"])

        assert result.exit_code == 0
        assert calls[0]["serial_path"] == "ttyUSB0"


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
