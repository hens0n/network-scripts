# Network Scripts

Utilities for working with network device console connections, especially capturing Cisco IOS/IOS-XE transcripts over serial.

## Replacement workflows

Run Python workflows through `uv` so the project-managed dependencies and console entry point are used.

### Record the Latest Serial Device

```sh
uv run network-scripts serial watch
```

`serial watch` waits for a newly attached Serial Device, prints the detected path, and records it as the Latest Serial Device in `.network-scripts/latest-serial-device.json`. Later Cisco commands use that recorded Serial Device unless `--serial` is provided.

### Capture a Config Dump

```sh
uv run network-scripts cisco dump
```

`cisco dump` logs in to a Cisco Device, enters privileged mode, runs diagnostic commands plus `show running-config`, and writes a timestamped `config-dump-YYYYMMDD-HHMMSS.txt` file by default. Credentials are resolved from CLI options, then `IOS_USER`, `IOS_PASS`, and `IOS_ENABLE`, then interactive prompts.

Useful options:

```sh
uv run network-scripts cisco dump --serial /dev/cu.usbserial-120 --baud 9600 --out my-config-dump.txt
```

### Capture a Diagnostic Dump

```sh
uv run network-scripts cisco dump --no-enable
```

A Diagnostic Dump skips privileged mode and does not run `show running-config`. It captures only non-privileged diagnostics (`terminal length 0`, `show version`, and `show ip interface brief`) and writes a timestamped `diagnostic-dump-YYYYMMDD-HHMMSS.txt` file by default. Use this when the Cisco Device login works but an enable secret is unavailable; the resulting explanation warns that the running configuration was not captured.

### Explain a dump as HTML

```sh
uv run network-scripts cisco explain INPUT
```

`cisco explain` renders a Config Dump, Diagnostic Dump, or legacy raw transcript as a self-contained HTML dashboard. By default it writes `<input-stem>.html`; pass `--out` or `-o` to choose the output path.

```sh
uv run network-scripts cisco explain INPUT --out dashboard.html
```

## Feature parity gate

The legacy `scripts/` directory stays until the uv-managed Python CLI reaches feature parity. Before deleting `scripts/`, verify:

- [ ] `uv run network-scripts serial watch` replaces `scripts/watch-serial-devices.sh` for detecting and recording the Latest Serial Device.
- [ ] `uv run network-scripts cisco dump` replaces privileged Config Dump capture from `scripts/dump-cisco-config.sh`, `scripts/dump-cisco-config.py`, and `scripts/dump-cisco-config.exp`.
- [ ] `uv run network-scripts cisco dump --no-enable` supports Diagnostic Dump capture without requiring an enable secret.
- [ ] `uv run network-scripts cisco explain INPUT` replaces `scripts/explain-cisco-config.py` for HTML explanation.
- [ ] Dump files include network-scripts metadata headers without credentials.
- [ ] Diagnostic Dump explanations visibly warn that `show running-config` was not captured.
- [ ] `npm run test` and `npm run typecheck` pass after deletion.

## Development

Install dependencies and run commands through `uv`:

```sh
uv run network-scripts --help
uv run network-scripts serial --help
uv run network-scripts cisco --help
uv run pytest
```

Project-level feedback loops are exposed through npm scripts:

```sh
npm run test
npm run typecheck
```
