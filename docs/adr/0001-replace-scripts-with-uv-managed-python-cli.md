# Replace scripts with a uv-managed Python CLI

We will replace the ad-hoc shell, Expect, and Python scripts with a uv-managed Python CLI using Typer and pyserial. The CLI will provide serial device watching, Cisco Device dump capture, and HTML explanation commands while keeping the underlying logic in testable Python modules. The existing `scripts/` directory stays until feature parity is reached, then it can be deleted; this trades the simplicity of standalone scripts for a more reliable, testable app workflow that still runs from the command line with `uv`.
