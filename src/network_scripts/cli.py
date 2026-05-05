import os
from pathlib import Path
from typing import Optional

import typer

from network_scripts import cisco_dump, serial_devices

app = typer.Typer(
    help="Utilities for Cisco Device console workflows.",
    no_args_is_help=True,
)
serial_app = typer.Typer(
    help="Work with Serial Device discovery and state.",
    no_args_is_help=True,
)
cisco_app = typer.Typer(
    help="Capture and explain Cisco Device dumps.",
    no_args_is_help=True,
)


@serial_app.callback()
def serial() -> None:
    """Work with Serial Device discovery and state."""


@serial_app.command("watch")
def watch_serial_device(
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        min=0.0,
        help="Seconds to wait for a newly added Serial Device.",
    ),
    path_only: bool = typer.Option(
        False,
        "--path-only",
        help="Print only the detected Serial Device path.",
    ),
    poll_interval: float = typer.Option(
        1.0,
        "--poll-interval",
        min=0.01,
        help="Seconds between Serial Device discovery polls.",
        hidden=True,
    ),
) -> None:
    """Watch for a new Serial Device and record it as the Latest Serial Device."""
    try:
        path = serial_devices.wait_for_new_serial_device(
            timeout=timeout,
            poll_interval=poll_interval,
        )
    except serial_devices.SerialDeviceWatchTimeout as exc:
        typer.echo(str(exc), err=True)
        typer.echo(
            "Connect a Serial Device and rerun `uv run network-scripts serial watch`.",
            err=True,
        )
        raise typer.Exit(1) from exc

    serial_devices.write_latest_serial_device(path)
    if path_only:
        typer.echo(path)
    else:
        typer.echo(f"Detected Serial Device: {path}")
        typer.echo("Recorded Latest Serial Device in .network-scripts/latest-serial-device.json")


@cisco_app.callback()
def cisco() -> None:
    """Capture and explain Cisco Device dumps."""


@cisco_app.command("dump")
def dump_cisco_device(
    serial: Optional[str] = typer.Option(
        None,
        "--serial",
        help="Serial Device path to use instead of the recorded Latest Serial Device.",
    ),
    baud: int = typer.Option(
        9600,
        "--baud",
        min=1,
        help="Serial baud rate.",
    ),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Config Dump output path. Defaults to config-dump-YYYYMMDD-HHMMSS.txt.",
    ),
    username: Optional[str] = typer.Option(
        None,
        "--user",
        "--username",
        help="Cisco Device login username. Defaults to IOS_USER, then an interactive prompt.",
    ),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        help="Cisco Device login password. Defaults to IOS_PASS, then an interactive prompt.",
    ),
    enable_secret: Optional[str] = typer.Option(
        None,
        "--enable",
        "--enable-secret",
        help="Cisco Device enable secret. Defaults to IOS_ENABLE, then an interactive prompt.",
    ),
    login_timeout: float = typer.Option(
        60.0,
        "--login-timeout",
        min=0.01,
        help="Seconds to wait while logging in.",
    ),
    command_timeout: float = typer.Option(
        120.0,
        "--command-timeout",
        min=0.01,
        help="Seconds to wait for each Cisco Device command to finish.",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Write debug tracing to stderr. DEBUG=1 also enables tracing.",
    ),
) -> None:
    """Capture a Config Dump from a Cisco Device."""
    try:
        serial_path = serial_devices.resolve_serial_device(explicit_path=serial)
        credentials = cisco_dump.resolve_credentials(
            username=username,
            password=password,
            enable_secret=enable_secret,
            prompt=lambda label, hide: typer.prompt(label, hide_input=hide),
        )
        output_path = out or cisco_dump.default_output_path()
        cisco_dump.capture_config_dump(
            serial_path=serial_path,
            baud=baud,
            credentials=credentials,
            output_path=output_path,
            login_timeout=login_timeout,
            command_timeout=command_timeout,
            debug=debug or os.environ.get("DEBUG") == "1",
        )
    except serial_devices.SerialDeviceResolutionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except cisco_dump.CiscoDumpError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc


app.add_typer(serial_app, name="serial")
app.add_typer(cisco_app, name="cisco")


if __name__ == "__main__":
    app()
