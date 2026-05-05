# Network Scripts

Utilities for working with network device console connections, especially capturing Cisco IOS/IOS-XE configuration transcripts over serial.

## Language

**Serial Device**:
A local operating-system device path that represents a physical console adapter connected to a network device.
_Avoid_: Port, cable, adapter when referring to the OS path itself

**Cisco Device**:
A network device running Cisco IOS or IOS-XE that is accessed through its console interface.
_Avoid_: Router when the device may be a switch or other Cisco network device

**Config Dump**:
A captured transcript of diagnostic and configuration commands from a Cisco Device, including the running configuration.
_Avoid_: Backup, export

**Diagnostic Dump**:
A captured transcript of non-privileged diagnostic commands from a Cisco Device, excluding the running configuration.
_Avoid_: Config Dump when the running configuration is absent

**Latest Serial Device**:
The most recently added Serial Device recorded by the app for use as a default in later commands.
_Avoid_: Current port, default cable

## Relationships

- A **Serial Device** provides console access to zero or one currently connected **Cisco Device**.
- The **Latest Serial Device** is one **Serial Device** selected by observing device-plug events.
- A **Config Dump** is captured from exactly one **Cisco Device** through one **Serial Device**.
- A **Diagnostic Dump** is captured from exactly one **Cisco Device** through one **Serial Device** without entering privileged mode.

## Example dialogue

> **Dev:** "Should the app use the newest **Serial Device** automatically for the **Config Dump**?"
> **Domain expert:** "Yes, but only as a convenience default — users still need to be able to specify the **Serial Device** explicitly."

## Flagged ambiguities

- "router" appears in existing script output names, but the tool should say **Cisco Device** because the target may be a router, switch, or other IOS/IOS-XE device.
