# Replace scripts with a uv-managed Python CLI

We replaced the ad-hoc shell, Expect, and Python scripts with a uv-managed Python CLI using Typer and pyserial. The CLI provides serial device watching, Cisco Device Config Dump capture, Cisco Device Diagnostic Dump capture, and HTML explanation commands while keeping the underlying logic in testable Python modules. After feature parity was reached, the legacy `scripts/` directory was deleted; this trades the simplicity of standalone scripts for a more reliable, testable app workflow that still runs from the command line with `uv`.
