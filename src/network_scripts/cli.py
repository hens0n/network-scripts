import os
from pathlib import Path
from typing import Optional

import typer

from network_scripts import cisco_dump, cisco_explain, serial_devices

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


@cisco_app.command("explain")
def explain_cisco_dump(
    input_path: Path = typer.Argument(
        ...,
        metavar="INPUT",
        help="Config Dump or legacy raw transcript to render as HTML.",
    ),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        "-o",
        help="HTML output path. Defaults to <input-stem>.html.",
    ),
) -> None:
    """Render a Config Dump as an HTML dashboard."""
    if not input_path.exists():
        typer.echo(f"error: {input_path} not found", err=True)
        raise typer.Exit(1)

    result = cisco_explain.explain_dump(input_path, out)
    if result.warning:
        typer.echo(f"warning: Diagnostic Dump: {result.warning}", err=True)
    typer.echo(f"wrote {result.output_path} ({result.output_path.stat().st_size:,} bytes)")
    typer.echo(f"  hostname:   {result.hostname}")
    typer.echo(f"  version:    {result.version.software} {result.version.version}")
    typer.echo(f"  model:      {result.version.model}")
    typer.echo(
        f"  interfaces: {result.interface_count} from brief table; "
        f"{result.running_interface_count} in running-config"
    )
    typer.echo(f"  blocks:     {result.block_count}")


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
    no_enable: bool = typer.Option(
        False,
        "--no-enable",
        help="Capture a Diagnostic Dump without entering privileged mode or running show running-config.",
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
    """Capture a Config Dump or Diagnostic Dump from a Cisco Device."""
    try:
        serial_path = serial_devices.resolve_serial_device(explicit_path=serial)
        enable = not no_enable
        credentials = cisco_dump.resolve_credentials(
            username=username,
            password=password,
            enable_secret=enable_secret,
            prompt=lambda label, hide: typer.prompt(label, hide_input=hide),
            require_enable_secret=enable,
        )
        output_path = out or cisco_dump.default_output_path(enable=enable)
        cisco_dump.capture_config_dump(
            serial_path=serial_path,
            baud=baud,
            credentials=credentials,
            output_path=output_path,
            login_timeout=login_timeout,
            command_timeout=command_timeout,
            enable=enable,
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
