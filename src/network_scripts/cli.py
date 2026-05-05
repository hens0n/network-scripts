import typer

from network_scripts import serial_devices

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


app.add_typer(serial_app, name="serial")
app.add_typer(cisco_app, name="cisco")


if __name__ == "__main__":
    app()
