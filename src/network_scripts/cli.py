import typer

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


@cisco_app.callback()
def cisco() -> None:
    """Capture and explain Cisco Device dumps."""


app.add_typer(serial_app, name="serial")
app.add_typer(cisco_app, name="cisco")


if __name__ == "__main__":
    app()
