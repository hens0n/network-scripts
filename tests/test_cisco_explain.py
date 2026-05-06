from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from network_scripts.cli import app


runner = CliRunner()


def test_cisco_explain_reads_metadata_dump_and_defaults_to_input_stem_html() -> None:
    transcript = """--- network-scripts dump metadata ---
type: config-dump
captured_at: 2026-05-05T12:34:56Z
serial_device: /dev/ttyUSB0
baud: 9600
hostname: Switch
--- transcript ---
Switch#show version
Cisco IOS XE Software, Version 17.13.01a
ROM: IOS-XE ROMMON
Switch uptime is 1 day, 2 hours
cisco C9300-24P (X86) processor
Processor board ID ABC123
System image file is \"flash:packages.conf\"
Switch#show ip interface brief
Interface              IP-Address      OK? Method Status                Protocol
GigabitEthernet1/0/1   10.0.0.1        YES manual up                    up
Switch#show running-config
Building configuration...
hostname Switch
interface GigabitEthernet1/0/1
 description Uplink
 ip address 10.0.0.1 255.255.255.0
end
Switch#
"""

    with runner.isolated_filesystem():
        Path("config-dump.txt").write_text(transcript, encoding="utf-8")

        result = runner.invoke(app, ["cisco", "explain", "config-dump.txt"])

        assert result.exit_code == 0, result.output
        html = Path("config-dump.html").read_text(encoding="utf-8")
        assert "Switch — Cisco config dashboard" in html
        assert "Cisco IOS XE 17.13.01a" in html
        assert "GigabitEthernet1/0/1" in html
        assert "Uplink" in html
        assert "wrote config-dump.html" in result.output


def test_cisco_explain_warns_when_rendering_diagnostic_dump() -> None:
    transcript = """--- network-scripts dump metadata ---
type: diagnostic-dump
captured_at: 2026-05-05T12:34:56Z
serial_device: /dev/ttyUSB0
baud: 9600
hostname: Switch
--- transcript ---
Switch>show version
Cisco IOS XE Software, Version 17.13.01a
ROM: IOS-XE ROMMON
Switch uptime is 1 day, 2 hours
cisco C9300-24P (X86) processor
Processor board ID ABC123
System image file is \"flash:packages.conf\"
Switch>show ip interface brief
Interface              IP-Address      OK? Method Status                Protocol
GigabitEthernet1/0/1   10.0.0.1        YES manual up                    up
Switch>
"""

    with runner.isolated_filesystem():
        Path("diagnostic-dump.txt").write_text(transcript, encoding="utf-8")

        result = runner.invoke(app, ["cisco", "explain", "diagnostic-dump.txt"])

        assert result.exit_code == 0, result.output
        html = Path("diagnostic-dump.html").read_text(encoding="utf-8")
        assert "Diagnostic Dump" in result.output
        assert "show running-config was not captured" in result.output
        assert "Diagnostic Dump" in html
        assert "No running configuration was captured" in html
        assert "Cisco IOS XE 17.13.01a" in html
        assert "GigabitEthernet1/0/1" in html


def test_cisco_explain_warns_when_running_config_is_missing_from_legacy_transcript() -> None:
    transcript = """Legacy#show version
Cisco IOS Software, Version 15.9(3)M
Legacy#show ip interface brief
Interface              IP-Address      OK? Method Status                Protocol
GigabitEthernet0/0/0   unassigned      YES unset  administratively down down
Legacy#
"""

    with runner.isolated_filesystem():
        Path("legacy-diagnostic.txt").write_text(transcript, encoding="utf-8")

        result = runner.invoke(app, ["cisco", "explain", "legacy-diagnostic.txt"])

        assert result.exit_code == 0, result.output
        html = Path("legacy-diagnostic.html").read_text(encoding="utf-8")
        assert "show running-config was not captured" in result.output
        assert "No running configuration was captured" in html
        assert "GigabitEthernet0/0/0" in html


def test_cisco_explain_tolerates_legacy_raw_transcript_and_honors_out_option() -> None:
    transcript = """Legacy#show version
Cisco IOS Software, Version 15.9(3)M
ROM: IOS ROMMON
Legacy uptime is 3 weeks
Cisco ISR4331/K9 (1RU) processor
Processor board ID FOC1234
System image file is \"bootflash:isr4300-universalk9.bin\"
Legacy#show ip interface brief
Interface              IP-Address      OK? Method Status                Protocol
GigabitEthernet0/0/0   unassigned      YES unset  administratively down down
Legacy#show running-config
hostname Legacy
username admin privilege 15 secret 9 $9$hash
line vty 0 4
 login local
end
Legacy#
"""

    with runner.isolated_filesystem():
        Path("legacy.txt").write_text(transcript, encoding="utf-8")

        result = runner.invoke(app, ["cisco", "explain", "legacy.txt", "--out", "dashboard.html"])

        assert result.exit_code == 0, result.output
        html = Path("dashboard.html").read_text(encoding="utf-8")
        assert "Legacy — Cisco config dashboard" in html
        assert "Cisco IOS 15.9(3)M" in html
        assert "Users &amp; Access Control" in html
        assert "Console / SSH Access" in html
        assert "wrote dashboard.html" in result.output
