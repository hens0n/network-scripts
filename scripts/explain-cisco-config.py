#!/usr/bin/env python3
"""Render a Cisco IOS/IOS-XE config transcript as a friendly HTML dashboard.

Reads the transcript produced by dump-cisco-config.sh (which contains
`show version`, `show ip interface brief`, and `show running-config`) and
generates a single self-contained HTML page that explains the device's
configuration in plain English for someone unfamiliar with Cisco.

Usage:
    scripts/explain-cisco-config.py [input.txt] [-o dashboard.html]
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Transcript splitting
# ---------------------------------------------------------------------------

PROMPT_RE = re.compile(r"^(?P<host>[\w\-.]+)#(?P<cmd>[^\n\r]*)$", re.MULTILINE)


def extract_command_output(transcript: str, command: str) -> str:
    """Return the output between `<host>#<command>` and the next prompt."""
    pattern = re.compile(
        rf"^(?P<host>[\w\-.]+)#\s*{re.escape(command)}\s*$",
        re.MULTILINE,
    )
    m = pattern.search(transcript)
    if not m:
        return ""
    host = m.group("host")
    start = m.end()
    end_m = re.search(rf"^{re.escape(host)}#", transcript[start:], re.MULTILINE)
    end = start + end_m.start() if end_m else len(transcript)
    return transcript[start:end].strip("\r\n ")


def find_hostname(transcript: str) -> str:
    m = PROMPT_RE.search(transcript)
    return m.group("host") if m else "unknown"


# ---------------------------------------------------------------------------
# `show version` parser
# ---------------------------------------------------------------------------

@dataclass
class VersionInfo:
    raw: str = ""
    software: str = ""
    version: str = ""
    rommon: str = ""
    uptime: str = ""
    model: str = ""
    serial: str = ""
    image: str = ""
    license: str = ""


def parse_show_version(text: str) -> VersionInfo:
    info = VersionInfo(raw=text)
    if not text:
        return info

    # "Cisco IOS XE Software, Version 17.13.01a"
    m = re.search(r"Cisco IOS XE Software,\s*Version\s+(\S+)", text)
    if m:
        info.software = "Cisco IOS XE"
        info.version = m.group(1)
    else:
        m = re.search(r"Cisco IOS Software.*Version\s+([0-9A-Za-z.\-()]+)", text)
        if m:
            info.software = "Cisco IOS"
            info.version = m.group(1)

    m = re.search(r"ROM:\s*([^\r\n]+)", text)
    if m:
        info.rommon = m.group(1).strip()

    m = re.search(r"uptime is\s+([^\r\n]+)", text)
    if m:
        info.uptime = m.group(1).strip()

    # System image file: "bootflash:..." or similar
    m = re.search(r"System image file is\s+\"([^\"]+)\"", text)
    if m:
        info.image = m.group(1).strip()

    # "cisco IR1835-K9 (..." or "Cisco IR1835-K9 ..."
    m = re.search(r"^[Cc]isco\s+(\S+)\s+\(", text, re.MULTILINE)
    if m:
        info.model = m.group(1).strip()

    m = re.search(r"Processor board ID\s+(\S+)", text)
    if m:
        info.serial = m.group(1).strip()

    m = re.search(r"License Level:\s*(\S+)", text)
    if m:
        info.license = m.group(1).strip()

    return info


# ---------------------------------------------------------------------------
# `show ip interface brief` parser
# ---------------------------------------------------------------------------

@dataclass
class BriefInterface:
    name: str
    ip: str
    ok: str
    method: str
    status: str
    protocol: str


def parse_show_ip_interface_brief(text: str) -> list[BriefInterface]:
    interfaces: list[BriefInterface] = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("Interface"):
            continue
        # Cisco's brief table is whitespace-separated with possibly multi-word status.
        # Example: "GigabitEthernet0/0/0  unassigned  YES NVRAM  administratively down  down"
        parts = re.split(r"\s{2,}|\t+", line.strip())
        if len(parts) < 5:
            parts = line.split()
            if len(parts) < 6:
                continue
            interfaces.append(BriefInterface(
                name=parts[0], ip=parts[1], ok=parts[2], method=parts[3],
                status=" ".join(parts[4:-1]), protocol=parts[-1],
            ))
        else:
            # parts: name, ip, "OK? Method", status, protocol  (varies)
            # fall back to a tighter split
            tokens = line.split()
            if len(tokens) >= 6:
                interfaces.append(BriefInterface(
                    name=tokens[0], ip=tokens[1], ok=tokens[2], method=tokens[3],
                    status=" ".join(tokens[4:-1]), protocol=tokens[-1],
                ))
    return interfaces


# ---------------------------------------------------------------------------
# `show running-config` parser
# ---------------------------------------------------------------------------

@dataclass
class ConfigBlock:
    header: str
    lines: list[str] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join([self.header] + self.lines)


def parse_running_config(text: str) -> list[ConfigBlock]:
    blocks: list[ConfigBlock] = []
    current: ConfigBlock | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("!"):
            # blank separator; end of current block context but keep block open
            # so multi-line interfaces / etc. don't get split unintentionally.
            if current is not None and current.lines:
                blocks.append(current)
                current = None
            continue
        if line.startswith(" "):
            if current is None:
                current = ConfigBlock(header="(orphan)")
            current.lines.append(line)
            continue
        # New top-level command.
        if current is not None:
            blocks.append(current)
        current = ConfigBlock(header=line)
    if current is not None:
        blocks.append(current)
    return blocks


# ---------------------------------------------------------------------------
# Categorization & explanations
# ---------------------------------------------------------------------------

CATEGORIES = [
    ("identity",   "Identity & Boot",        "Hostname, IOS version, boot image, and other top-level system settings."),
    ("users",      "Users & Access Control", "Local user accounts, enable secret, and AAA (authentication, authorization, accounting)."),
    ("services",   "Network Services",       "DNS, NTP, SNMP, logging, and similar always-on infrastructure services."),
    ("interfaces", "Interfaces",             "Physical and virtual network interfaces — what's plugged in and how it's configured."),
    ("vlans",      "VLANs & Port Mapping",   "Which physical ports belong to which VLAN, and where each VLAN's gateway lives."),
    ("routing",    "Routing",                "Static routes and dynamic routing protocols (OSPF, BGP, EIGRP)."),
    ("security",   "Security & Filtering",   "Access lists (firewall rules), VPN/crypto, and login banners."),
    ("lines",      "Console / SSH Access",   "How you get into the device — console port, telnet/SSH (vty) lines."),
    ("apphosting", "App Hosting (IOx)",      "Cisco IOx — runs Docker-style containers on the router. Used for the Starlink dashboard."),
    ("other",      "Other Configuration",    "Anything that didn't fit one of the categories above."),
]

CATEGORY_KEYS = [c[0] for c in CATEGORIES]


def categorize(block: ConfigBlock) -> str:
    h = block.header
    if h.startswith(("hostname", "version", "boot ", "service ", "no service ",
                     "platform ", "no platform ", "memory-size", "memory ",
                     "license ", "diagnostic ")):
        return "identity"
    if h.startswith(("username ", "enable ", "aaa ")):
        return "users"
    if h.startswith(("ip domain", "ip name-server", "ip dhcp", "ip dns",
                     "ntp ", "clock ", "snmp-server", "logging ",
                     "ip http", "no ip http", "ip ssh")):
        return "services"
    if h.startswith("interface ") or h.startswith("vlan ") or h.startswith("vrf "):
        return "interfaces"
    if h.startswith(("ip route", "ipv6 route", "router ", "ip prefix-list",
                     "route-map", "ip as-path")):
        return "routing"
    if h.startswith(("access-list", "ip access-list", "ipv6 access-list",
                     "crypto ", "object-group", "class-map", "policy-map",
                     "banner ", "login ", "parser ", "no banner")):
        return "security"
    if h.startswith("line "):
        return "lines"
    if h.startswith(("app-hosting", "iox", "no iox")):
        return "apphosting"
    return "other"


def header_explanation(block: ConfigBlock) -> str:
    """Return a one-liner explaining the top-level command, or '' if generic."""
    h = block.header
    if h.startswith("hostname "):
        return f"Sets the device's name to {h.split(maxsplit=1)[1]} (shown in CLI prompts and logs)."
    if h.startswith("version "):
        return f"Configuration was written by IOS version {h.split(maxsplit=1)[1]}."
    if h.startswith("boot system"):
        return "Tells the router which IOS image to boot on next reload."
    if h.startswith("service "):
        return f"Enables a global system service: <code>{html.escape(h)}</code>"
    if h.startswith("no service "):
        return f"Disables a global system service: <code>{html.escape(h)}</code>"
    if h == "no ip http server":
        return "Plain HTTP web server is OFF."
    if h == "ip http server":
        return "Plain HTTP web server is ON (needed for the IOx Local Manager web GUI)."
    if h == "no ip http secure-server":
        return "HTTPS web server is OFF."
    if h == "ip http secure-server":
        return "HTTPS web server is ON (recommended for the web GUI)."
    if h.startswith("ip http authentication"):
        return f"Sets how the web GUI authenticates users: <code>{html.escape(h)}</code>"
    if h.startswith("username "):
        m = re.match(r"username\s+(\S+)\s+privilege\s+(\d+)", h)
        if m:
            user, priv = m.group(1), int(m.group(2))
            level = "full admin (privilege 15)" if priv == 15 else f"limited (privilege {priv})"
            return f"Local user <strong>{html.escape(user)}</strong> with {level}. Stored locally on the device."
        m = re.match(r"username\s+(\S+)", h)
        if m:
            return f"Local user <strong>{html.escape(m.group(1))}</strong> defined on the device."
    if h.startswith("enable secret"):
        return "Sets the password to enter privileged-EXEC ('enable' / # prompt) mode. Hashed in the config."
    if h.startswith("enable password"):
        return "Sets a (less secure, reversible) enable password. Prefer 'enable secret'."
    if h == "aaa new-model":
        return "Turns on the modern AAA framework (authentication, authorization, accounting). Without this, all auth uses simple line passwords."
    if h.startswith("aaa authentication"):
        return f"Defines an AAA authentication method list: <code>{html.escape(h)}</code>"
    if h.startswith("aaa authorization"):
        return f"Defines an AAA authorization method list: <code>{html.escape(h)}</code>"
    if h.startswith("ip domain "):
        return f"Sets the device's DNS domain context: <code>{html.escape(h)}</code>"
    if h.startswith("ip name-server"):
        return f"Configures upstream DNS servers: <code>{html.escape(h)}</code>"
    if h.startswith("ntp server"):
        return f"Adds an NTP time server: <code>{html.escape(h)}</code>"
    if h.startswith("clock timezone"):
        return f"Sets the local timezone: <code>{html.escape(h)}</code>"
    if h.startswith("snmp-server"):
        return f"SNMP (network monitoring) configuration: <code>{html.escape(h)}</code>"
    if h.startswith("logging "):
        return f"Where the router sends syslog messages: <code>{html.escape(h)}</code>"
    if h.startswith("ip route "):
        m = re.match(r"ip route\s+(\S+)\s+(\S+)\s+(\S+)", h)
        if m:
            return (f"Static route: send traffic for <code>{m.group(1)}/{m.group(2)}</code> "
                    f"to next hop <code>{m.group(3)}</code>.")
        return f"Static IPv4 route: <code>{html.escape(h)}</code>"
    if h.startswith("router "):
        proto = h.split()[1] if len(h.split()) > 1 else "?"
        return f"Enables dynamic routing protocol: <strong>{html.escape(proto.upper())}</strong>."
    if h.startswith("access-list "):
        return f"Numbered access-list (firewall rule): <code>{html.escape(h)}</code>"
    if h.startswith("ip access-list"):
        return f"Named IP access-list (firewall rule set): <code>{html.escape(h)}</code>"
    if h.startswith("crypto "):
        return f"Cryptographic / VPN configuration: <code>{html.escape(h)}</code>"
    if h.startswith("banner "):
        return "Login banner shown to users when they connect."
    if h.startswith("line con"):
        return "Console line settings (the physical RJ45/USB serial console port)."
    if h.startswith("line aux"):
        return "Auxiliary line settings (rarely used; usually for legacy modems)."
    if h.startswith("line vty"):
        return "Virtual terminal lines — used for remote SSH/Telnet connections."
    if h == "iox":
        return "IOx (Cisco's container hosting framework) is enabled. Required to run the Starlink dashboard package."
    if h == "no iox":
        return "IOx container hosting is disabled."
    if h.startswith("app-hosting appid"):
        appid = h.split()[-1]
        return f"App-hosting configuration block for IOx app <strong>{html.escape(appid)}</strong>."
    if h.startswith("interface "):
        return ""  # detailed in the interface card itself
    return ""


def explain_interface_block(block: ConfigBlock) -> tuple[str, list[tuple[str, str]]]:
    """Return (summary, [(label, value), ...]) for an interface block."""
    rows: list[tuple[str, str]] = []
    description = ""
    ip_addr = ""
    shutdown = False
    is_switchport = False
    access_vlan = ""
    voice_vlan = ""
    trunk_native = ""
    trunk_allowed = ""
    switchport_mode = ""
    vrf = ""
    speed = ""
    extras: list[str] = []
    for ln in block.lines:
        s = ln.strip()
        if s.startswith("description "):
            description = s[len("description "):]
        elif s.startswith("ip address "):
            ip_addr = s[len("ip address "):]
        elif s == "shutdown":
            shutdown = True
        elif s == "no shutdown":
            shutdown = False
        elif s.startswith("switchport"):
            is_switchport = True
            m = re.match(r"switchport access vlan\s+(\d+)$", s)
            if m:
                access_vlan = m.group(1)
                continue
            m = re.match(r"switchport voice vlan\s+(\d+)$", s)
            if m:
                voice_vlan = m.group(1)
                continue
            m = re.match(r"switchport trunk native vlan\s+(\d+)$", s)
            if m:
                trunk_native = m.group(1)
                continue
            m = re.match(r"switchport trunk allowed vlan(?:\s+add)?\s+(.+)$", s)
            if m:
                trunk_allowed = (trunk_allowed + "," + m.group(1)) if trunk_allowed else m.group(1)
                continue
            m = re.match(r"switchport mode\s+(\S+)$", s)
            if m:
                switchport_mode = m.group(1)
                continue
            extras.append(s)
        elif s.startswith("vrf forwarding "):
            vrf = s.split()[-1]
        elif s.startswith("speed "):
            speed = s.split(maxsplit=1)[1]
        else:
            extras.append(s)

    if description:
        rows.append(("Description", description))
    rows.append(("Admin status", "Disabled (shutdown)" if shutdown else "Enabled"))
    if ip_addr:
        rows.append(("IPv4 address", ip_addr))
    if vrf:
        rows.append(("VRF", vrf))
    if is_switchport:
        mode_label = f"Layer-2 switchport ({switchport_mode})" if switchport_mode else "Layer-2 switchport"
        rows.append(("Mode", mode_label))
    if access_vlan:
        rows.append(("Access VLAN", f"VLAN {access_vlan}"))
    if voice_vlan:
        rows.append(("Voice VLAN", f"VLAN {voice_vlan}"))
    if trunk_native:
        rows.append(("Trunk native VLAN", f"VLAN {trunk_native}"))
    if trunk_allowed:
        rows.append(("Trunk allowed VLANs", trunk_allowed))
    if speed:
        rows.append(("Speed", speed))
    if extras:
        rows.append(("Other settings", "; ".join(extras)))

    summary_bits = []
    if description:
        summary_bits.append(description)
    if ip_addr:
        summary_bits.append(f"IP {ip_addr.split()[0]}")
    if access_vlan:
        summary_bits.append(f"access VLAN {access_vlan}")
    if trunk_allowed:
        summary_bits.append(f"trunk: {trunk_allowed}")
    if shutdown:
        summary_bits.append("administratively down")
    elif is_switchport and not access_vlan and not trunk_allowed:
        summary_bits.append("L2 switchport")
    summary = " — ".join(summary_bits) if summary_bits else "no extra config"
    return summary, rows


# ---------------------------------------------------------------------------
# VLAN cross-reference
# ---------------------------------------------------------------------------

@dataclass
class VlanInfo:
    vid: int
    name: str = ""
    svi_ip: str = ""
    svi_shutdown: bool = False
    access_ports: list[str] = field(default_factory=list)
    trunk_ports: list[str] = field(default_factory=list)
    voice_ports: list[str] = field(default_factory=list)
    native_on: list[str] = field(default_factory=list)
    app_hosting: list[str] = field(default_factory=list)


def expand_vlan_list(spec: str) -> list[int]:
    """Expand '1,3-5,10' into [1,3,4,5,10]. Tolerates 'all', 'none', spaces."""
    out: list[int] = []
    for raw in spec.replace(" ", "").split(","):
        if not raw or raw in ("all", "none"):
            continue
        if "-" in raw:
            try:
                a, b = raw.split("-", 1)
                out.extend(range(int(a), int(b) + 1))
            except ValueError:
                continue
        else:
            try:
                out.append(int(raw))
            except ValueError:
                continue
    return out


def build_vlan_map(blocks: list[ConfigBlock]) -> dict[int, VlanInfo]:
    vlans: dict[int, VlanInfo] = {}

    def get(vid: int) -> VlanInfo:
        if vid not in vlans:
            vlans[vid] = VlanInfo(vid=vid)
        return vlans[vid]

    for b in blocks:
        h = b.header

        # "vlan 10" top-level definitions (with sub-line 'name X').
        m = re.match(r"vlan\s+(\d+)\s*$", h)
        if m:
            v = get(int(m.group(1)))
            for ln in b.lines:
                ms = re.match(r"\s*name\s+(.+)$", ln)
                if ms:
                    v.name = ms.group(1).strip()
            continue

        # "interface Vlan10" — SVI for that VLAN.
        m = re.match(r"interface Vlan(\d+)\s*$", h)
        if m:
            v = get(int(m.group(1)))
            for ln in b.lines:
                ms = re.match(r"\s*ip address\s+(.+)$", ln)
                if ms:
                    v.svi_ip = ms.group(1).strip()
                if ln.strip() == "shutdown":
                    v.svi_shutdown = True
            continue

        # Physical / sub-interface with switchport directives.
        if h.startswith("interface "):
            iface = h.split(maxsplit=1)[1]
            for ln in b.lines:
                s = ln.strip()
                m = re.match(r"switchport access vlan\s+(\d+)$", s)
                if m:
                    get(int(m.group(1))).access_ports.append(iface)
                    continue
                m = re.match(r"switchport voice vlan\s+(\d+)$", s)
                if m:
                    get(int(m.group(1))).voice_ports.append(iface)
                    continue
                m = re.match(r"switchport trunk native vlan\s+(\d+)$", s)
                if m:
                    get(int(m.group(1))).native_on.append(iface)
                    continue
                m = re.match(r"switchport trunk allowed vlan(?:\s+add)?\s+(.+)$", s)
                if m:
                    for vid in expand_vlan_list(m.group(1)):
                        get(vid).trunk_ports.append(iface)
                    continue
            continue

        # IOx app-hosting blocks: "vlan N guest-interface M" inside.
        if h.startswith("app-hosting appid "):
            appid = h.split()[-1]
            for ln in b.lines:
                m = re.match(r"\s*vlan\s+(\d+)\s+guest-interface\s+(\d+)\s*$", ln)
                if m:
                    vid, guest = int(m.group(1)), m.group(2)
                    get(vid).app_hosting.append(f"{appid} (guest-interface {guest})")

    # Dedupe lists while preserving order.
    for v in vlans.values():
        for attr in ("access_ports", "trunk_ports", "voice_ports", "native_on", "app_hosting"):
            seen: set[str] = set()
            new: list[str] = []
            for x in getattr(v, attr):
                if x not in seen:
                    seen.add(x)
                    new.append(x)
            setattr(v, attr, new)
    return vlans


def explain_app_hosting_block(block: ConfigBlock) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for ln in block.lines:
        s = ln.strip()
        if s.startswith("app-vnic"):
            rows.append(("Network", f"Container network interface: <code>{html.escape(s)}</code>"))
        elif s.startswith("guest-ipaddress"):
            rows.append(("Container IP", html.escape(s.replace("guest-ipaddress ", ""))))
        elif s.startswith("vlan "):
            rows.append(("VLAN binding", html.escape(s)))
        elif s.startswith("app-default-gateway"):
            rows.append(("Default gateway", html.escape(s.replace("app-default-gateway ", ""))))
        elif s.startswith("run-opts"):
            rows.append(("Docker run-opts", html.escape(s)))
        elif s.startswith("app-resource"):
            rows.append(("Resources", html.escape(s)))
        else:
            rows.append(("", html.escape(s)))
    return rows


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

CSS = """
:root {
  --bg: #f7f8fa;
  --card-bg: #ffffff;
  --border: #e1e4e8;
  --text: #1f2328;
  --muted: #57606a;
  --accent: #0969da;
  --good: #1a7f37;
  --bad: #cf222e;
  --warn: #9a6700;
  --code-bg: #f6f8fa;
}
* { box-sizing: border-box; }
body {
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  margin: 0; background: var(--bg); color: var(--text);
}
header.topbar {
  background: #24292f; color: #fff; padding: 16px 24px;
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;
}
header.topbar h1 { margin: 0; font-size: 20px; }
header.topbar .meta { font-size: 13px; color: #c8d1da; }
.summary {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  padding: 18px 24px; background: #fff; border-bottom: 1px solid var(--border);
}
.summary .item { padding: 8px 12px; border-left: 3px solid var(--accent); background: #fafbfc; }
.summary .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
.summary .value { font-size: 14px; font-weight: 600; word-break: break-word; }
nav.toc {
  padding: 12px 24px; background: #fff; border-bottom: 1px solid var(--border);
  display: flex; flex-wrap: wrap; gap: 16px;
}
nav.toc a { color: var(--accent); text-decoration: none; font-size: 13px; }
nav.toc a:hover { text-decoration: underline; }
main { padding: 24px; max-width: 1100px; margin: 0 auto; }
section.category { margin-bottom: 32px; }
section.category > h2 {
  margin: 0 0 8px 0; padding-bottom: 6px; border-bottom: 1px solid var(--border);
  font-size: 18px;
}
section.category > p.intro { margin: 0 0 16px 0; color: var(--muted); }
.card {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px;
  padding: 14px 16px; margin-bottom: 12px;
}
.card h3 {
  margin: 0 0 6px 0; font-size: 14px; font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  color: #1f2328; word-break: break-all;
}
.card .what { color: var(--muted); margin: 0 0 8px 0; font-size: 13px; }
.card .rows { display: grid; grid-template-columns: 160px 1fr; gap: 4px 14px; font-size: 13px; }
.card .rows dt { color: var(--muted); }
.card .rows dd { margin: 0; }
.card details { margin-top: 8px; }
.card details summary { cursor: pointer; color: var(--accent); font-size: 12px; }
.card details pre {
  background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px;
  padding: 8px 10px; margin: 8px 0 0; font-size: 12px; overflow-x: auto;
}
.badge {
  display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px;
  font-weight: 600; margin-left: 6px; vertical-align: middle;
}
.badge.good { background: #dafbe1; color: var(--good); }
.badge.bad  { background: #ffebe9; color: var(--bad); }
.badge.warn { background: #fff8c5; color: var(--warn); }
.badge.muted { background: #eaeef2; color: var(--muted); }
table.brief {
  width: 100%; border-collapse: collapse; font-size: 13px;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
}
table.brief th, table.brief td {
  border-bottom: 1px solid var(--border); padding: 6px 8px; text-align: left;
}
table.brief th { background: #f6f8fa; }
code { font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace; background: var(--code-bg); padding: 1px 4px; border-radius: 3px; }
"""


def status_badge(status: str) -> str:
    s = status.lower()
    if "administratively down" in s:
        return '<span class="badge muted">Disabled</span>'
    if "down" in s:
        return '<span class="badge bad">Down</span>'
    if "up" in s:
        return '<span class="badge good">Up</span>'
    return f'<span class="badge muted">{html.escape(status)}</span>'


def render_card(title: str, what: str, rows: list[tuple[str, str]] | None,
                raw: str, badges: str = "") -> str:
    parts = [f'<div class="card"><h3>{html.escape(title)}{badges}</h3>']
    if what:
        parts.append(f'<p class="what">{what}</p>')
    if rows:
        parts.append('<dl class="rows">')
        for label, value in rows:
            if label:
                parts.append(f'<dt>{html.escape(label)}</dt><dd>{value}</dd>')
            else:
                parts.append(f'<dt></dt><dd>{value}</dd>')
        parts.append('</dl>')
    if raw:
        parts.append(
            '<details><summary>raw config</summary>'
            f'<pre>{html.escape(raw)}</pre></details>'
        )
    parts.append('</div>')
    return "".join(parts)


def render_vlan_table(vlans: dict[int, VlanInfo]) -> str:
    if not vlans:
        return ('<div class="card"><h3>No VLANs detected</h3>'
                '<p class="what">No <code>vlan</code> definitions or <code>switchport</code> '
                'VLAN assignments were found in the running-config.</p></div>')
    rows = []
    for vid in sorted(vlans.keys()):
        v = vlans[vid]
        gateway = html.escape(v.svi_ip) if v.svi_ip else "<span class=\"badge muted\">no SVI</span>"
        if v.svi_ip and v.svi_shutdown:
            gateway += ' <span class="badge bad">shutdown</span>'
        access = ", ".join(html.escape(p) for p in v.access_ports) or "—"
        trunk = ", ".join(html.escape(p) for p in v.trunk_ports) or "—"
        native = ", ".join(html.escape(p) for p in v.native_on)
        if native:
            trunk = (trunk + "<br><span class=\"badge muted\">native on</span> " + native) if trunk != "—" \
                    else "<span class=\"badge muted\">native on</span> " + native
        voice = ", ".join(html.escape(p) for p in v.voice_ports)
        if voice:
            access = (access + "<br><span class=\"badge muted\">voice on</span> " + voice) if access != "—" \
                     else "<span class=\"badge muted\">voice on</span> " + voice
        apps = "<br>".join(html.escape(a) for a in v.app_hosting) or "—"
        rows.append(
            f'<tr><td><strong>{vid}</strong></td>'
            f'<td>{html.escape(v.name) or "—"}</td>'
            f'<td>{gateway}</td>'
            f'<td>{access}</td>'
            f'<td>{trunk}</td>'
            f'<td>{apps}</td></tr>'
        )
    return (
        '<div class="card"><h3>VLAN to port mapping</h3>'
        '<p class="what">For each VLAN: its name, gateway IP (the <code>interface VlanN</code> SVI), '
        'which physical/virtual ports use it as their access VLAN, which trunk ports carry it, '
        'and any IOx container interfaces tagged on it.</p>'
        '<table class="brief"><thead><tr>'
        '<th>VLAN</th><th>Name</th><th>Gateway (SVI)</th>'
        '<th>Access ports</th><th>Trunk ports</th><th>App-Hosting</th>'
        '</tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table></div>'
    )


def render_html(title: str, version: VersionInfo, brief: list[BriefInterface],
                blocks: list[ConfigBlock]) -> str:
    by_cat: dict[str, list[ConfigBlock]] = {k: [] for k in CATEGORY_KEYS}
    for b in blocks:
        by_cat[categorize(b)].append(b)
    vlans = build_vlan_map(blocks)

    # Summary tiles.
    summary_items = [
        ("Hostname", title),
        ("Software", f"{version.software} {version.version}".strip() or "(unknown)"),
        ("Model", version.model or "(unknown)"),
        ("Uptime", version.uptime or "(unknown)"),
        ("Image", version.image or "(unknown)"),
        ("License", version.license or "(unknown)"),
    ]
    summary_html = "".join(
        f'<div class="item"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div></div>'
        for label, value in summary_items
    )

    nav_html = "".join(
        f'<a href="#cat-{k}">{html.escape(t)}</a>'
        for k, t, _ in CATEGORIES
        if by_cat.get(k) or k == "interfaces" or (k == "vlans" and vlans)
    )

    sections_html: list[str] = []
    for key, name, intro in CATEGORIES:
        cat_blocks = by_cat.get(key, [])
        # interfaces always renders (for the brief table).
        # vlans renders if any VLAN was detected anywhere in the config.
        if not cat_blocks and key != "interfaces" and not (key == "vlans" and vlans):
            continue

        section_parts = [
            f'<section class="category" id="cat-{key}">',
            f'<h2>{html.escape(name)}</h2>',
            f'<p class="intro">{html.escape(intro)}</p>',
        ]

        if key == "vlans":
            section_parts.append(render_vlan_table(vlans))
            section_parts.append('</section>')
            sections_html.append("".join(section_parts))
            continue

        if key == "interfaces" and brief:
            section_parts.append('<div class="card">')
            section_parts.append('<h3>Live interface state (show ip interface brief)</h3>')
            section_parts.append('<p class="what">Quick view of every interface and whether it has a working IP and link.</p>')
            section_parts.append('<table class="brief">')
            section_parts.append('<thead><tr><th>Interface</th><th>IP</th><th>Status</th><th>Protocol</th></tr></thead><tbody>')
            for iface in brief:
                section_parts.append(
                    f'<tr><td>{html.escape(iface.name)}</td>'
                    f'<td>{html.escape(iface.ip)}</td>'
                    f'<td>{html.escape(iface.status)} {status_badge(iface.status)}</td>'
                    f'<td>{html.escape(iface.protocol)} {status_badge(iface.protocol)}</td></tr>'
                )
            section_parts.append('</tbody></table></div>')

        for b in cat_blocks:
            if key == "interfaces" and b.header.startswith("interface "):
                summary, rows = explain_interface_block(b)
                section_parts.append(render_card(b.header, summary, rows, b.text()))
            elif key == "apphosting" and b.header.startswith("app-hosting "):
                rows = explain_app_hosting_block(b)
                section_parts.append(render_card(
                    b.header,
                    "App-hosting configuration for an IOx container.",
                    rows, b.text(),
                ))
            else:
                what = header_explanation(b)
                rows = [("Sub-setting", html.escape(ln.strip())) for ln in b.lines] if b.lines else None
                section_parts.append(render_card(b.header, what, rows, b.text()))

        section_parts.append('</section>')
        sections_html.append("".join(section_parts))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — Cisco config dashboard</title>
<style>{CSS}</style>
</head>
<body>
<header class="topbar">
  <h1>{html.escape(title)}</h1>
  <div class="meta">Cisco configuration explainer</div>
</header>
<div class="summary">{summary_html}</div>
<nav class="toc">{nav_html}</nav>
<main>{''.join(sections_html)}</main>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="config.txt",
                        help="Input transcript file (default: config.txt)")
    parser.add_argument("-o", "--out", default="dashboard.html",
                        help="Output HTML path (default: dashboard.html)")
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 1

    transcript = src.read_text(encoding="utf-8", errors="replace")
    hostname = find_hostname(transcript)

    version = parse_show_version(extract_command_output(transcript, "show version"))
    brief = parse_show_ip_interface_brief(
        extract_command_output(transcript, "show ip interface brief")
    )
    running = extract_command_output(transcript, "show running-config")
    blocks = parse_running_config(running)

    out_path = Path(args.out)
    out_path.write_text(render_html(hostname, version, brief, blocks), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes)")
    print(f"  hostname:   {hostname}")
    print(f"  version:    {version.software} {version.version}")
    print(f"  model:      {version.model}")
    print(f"  interfaces: {len(brief)} from brief table; {sum(1 for b in blocks if b.header.startswith('interface ')) } in running-config")
    print(f"  blocks:     {len(blocks)} top-level config blocks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
