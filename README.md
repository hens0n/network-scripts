# Network Scripts

Utilities for working with network device console connections, especially capturing Cisco IOS/IOS-XE transcripts over serial.

## Development

Install dependencies and run commands through `uv`:

```sh
uv run network-scripts --help
uv run network-scripts serial --help
uv run network-scripts cisco --help
uv run pytest
```

The current CLI scaffold establishes the supported command groups. Cisco Device capture behavior remains in the legacy `scripts/` directory until feature parity is reached.
