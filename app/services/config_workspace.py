from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigSection:
    key: str
    title: str
    description: str
    lines: list[str]
    editable: bool = False
    note: str = ""


ZYXEL_CAPABILITIES = [
    "System/IP",
    "Time",
    "Port",
    "EEE",
    "Bandwidth Management",
    "Storm Control",
    "VLAN",
    "Guest VLAN",
    "Voice VLAN",
    "MAC Table",
    "Link Aggregation",
    "Loop Guard",
    "Mirror",
    "IGMP",
    "Spanning Tree",
    "LLDP",
    "QoS",
    "Port Security",
    "Port Isolation",
    "802.1X",
    "DoS",
    "AAA",
    "RADIUS",
    "TACACS+",
    "Syslog",
    "SNMP",
    "HTTP/HTTPS",
    "TELNET/SSH",
    "Users",
    "Remote Access Control",
    "Firmware",
    "Configuration Backup/Restore",
    "Certificates",
    "Diagnostics",
    "Ping/Trace",
    "Reboot",
]

EDGEOS_CAPABILITIES = [
    "Interfaces",
    "Switch/VLAN",
    "DHCP Server",
    "DNS/Static Host Mapping",
    "Firewall",
    "Source NAT",
    "Port Forwarding",
    "Static Routes",
    "GUI/SSH Services",
    "NTP/Timezone",
    "System Users",
    "VPN",
]


def get_capability_catalog(driver_type: str) -> list[str]:
    if driver_type == "zyxel-ssh":
        return ZYXEL_CAPABILITIES
    if driver_type == "edgeos-ssh":
        return EDGEOS_CAPABILITIES
    return []


def build_config_sections(driver_type: str, running_config: str, command_config: str = "") -> list[ConfigSection]:
    if driver_type == "edgeos-ssh":
        return _edgeos_sections(command_config or running_config)
    if driver_type == "zyxel-ssh":
        return _zyxel_sections(running_config)
    return []


def _normalized_lines(raw: str) -> list[str]:
    return [line.rstrip() for line in raw.splitlines() if line.strip()]


def _edgeos_sections(raw: str) -> list[ConfigSection]:
    lines = _normalized_lines(raw)
    groups: list[tuple[str, str, str, tuple[str, ...]]] = [
        ("interfaces", "Interfaces & VLANs", "Physische Ports, Switches, VLAN-Interfaces und Beschreibungen.", ("set interfaces ",)),
        ("firewall", "Firewall", "Globale Firewall- und Schutzoptionen.", ("set firewall ",)),
        ("dhcp_dns", "DHCP & DNS", "DHCP-Scopes, DNS-Dienst und statische Hostnamen.", ("set service dhcp-server ", "set service dns", "set system static-host-mapping ")),
        ("nat", "NAT & Port Forward", "Masquerading, DNAT und Port-Forward-Regeln.", ("set service nat ", "set port-forward ")),
        ("routing", "Routing", "Statische Routen und Routing-Protokolle.", ("set protocols ",)),
        ("services", "Services & Access", "GUI, SSH, Controller/UNMS und sonstige Services.", ("set service gui ", "set service ssh ", "set service unms", "set service ")),
        ("system", "System", "Hostname, NTP, Zeitzone und Logins.", ("set system ",)),
        ("vpn", "VPN", "VPN-spezifische Konfiguration.", ("set vpn",)),
    ]

    buckets: dict[str, list[str]] = {key: [] for key, *_ in groups}
    buckets["other"] = []

    for line in lines:
        assigned = False
        for key, _, _, prefixes in groups:
            if any(line.startswith(prefix) for prefix in prefixes):
                buckets[key].append(line)
                assigned = True
                break
        if not assigned:
            buckets["other"].append(line)

    sections: list[ConfigSection] = []
    for key, title, description, _ in groups:
        if not buckets[key]:
            continue
        sections.append(
            ConfigSection(
                key=key,
                title=title,
                description=description,
                lines=buckets[key],
                editable=True,
                note="Zeilen werden als echte EdgeOS-Konfigurationsbefehle ausgeführt. Entfernen bitte explizit als `delete ...` schreiben.",
            )
        )

    if buckets["other"]:
        sections.append(
            ConfigSection(
                key="other",
                title="Weitere Befehle",
                description="Nicht kategorisierte Zeilen aus der EdgeOS-Konfiguration.",
                lines=buckets["other"],
                editable=True,
                note="Auch hier bitte für Löschungen `delete ...` verwenden.",
            )
        )

    return sections


def _zyxel_sections(raw: str) -> list[ConfigSection]:
    sections: dict[str, list[str]] = {
        "system": [],
        "vlans": [],
        "security": [],
        "switching": [],
        "interfaces": [],
        "other": [],
    }

    current_chunk: list[str] = []
    for line in raw.splitlines():
        stripped = line.rstrip()
        if not stripped or stripped == "!":
            if current_chunk:
                _append_zyxel_chunk(sections, current_chunk)
                current_chunk = []
            continue
        current_chunk.append(stripped)

    if current_chunk:
        _append_zyxel_chunk(sections, current_chunk)

    result: list[ConfigSection] = []
    metadata = [
        (
            "system",
            "System & Management",
            "Management-IP, Gateway, DNS, Benutzer, SNMP, SSH/Telnet und globale Verwaltungsoptionen.",
        ),
        (
            "vlans",
            "VLANs & Voice",
            "VLAN-Definitionen, Voice VLAN und Management-VLAN.",
        ),
        (
            "security",
            "Security & AAA",
            "Port-Security, Zugriffslisten, Loop Guard, AAA, RADIUS und TACACS+.",
        ),
        (
            "switching",
            "Layer-2 Features",
            "Spanning Tree, LLDP, Mirroring, IGMP, QoS und sonstige Switch-Funktionen.",
        ),
        (
            "interfaces",
            "Interface-Blöcke",
            "Port-spezifische Switchport-, VLAN-, QoS- und Beschreibungszeilen.",
        ),
        (
            "other",
            "Weitere Konfiguration",
            "Nicht einsortierte Zeilen aus der Running-Config.",
        ),
    ]

    for key, title, description in metadata:
        if not sections[key]:
            continue
        result.append(
            ConfigSection(
                key=key,
                title=title,
                description=description,
                lines=sections[key],
                editable=False,
                note="Auf dem GS1900 ist die SSH-CLI auf diesem Gerät nur lesend. Für Vollzugriff nutzt die App unten die native Web-Bridge.",
            )
        )

    return result


def _append_zyxel_chunk(sections: dict[str, list[str]], chunk: list[str]) -> None:
    first = chunk[0].strip().lower()
    if first.startswith("interface "):
        sections["interfaces"].extend(chunk + [""])
        return

    if first.startswith(("vlan ", "voice-vlan", "management-vlan")):
        sections["vlans"].extend(chunk + [""])
        return

    if first.startswith(("port-security", "management access-list", "loop-guard", "dot1x", "aaa", "radius", "tacacs", "dos")):
        sections["security"].extend(chunk + [""])
        return

    if first.startswith(("spanning-tree", "lldp", "mirror", "igmp", "qos", "storm-control", "lag", "mac ")):
        sections["switching"].extend(chunk + [""])
        return

    if first.startswith(("ip ", "username ", "snmp ", "sntp", "http", "https", "telnet", "ssh", "clock")):
        sections["system"].extend(chunk + [""])
        return

    sections["other"].extend(chunk + [""])
