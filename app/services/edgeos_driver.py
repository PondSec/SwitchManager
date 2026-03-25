from __future__ import annotations

import re

from .ssh_client import SSHClientService, SSHExecutionError
from .switch_driver_base import SwitchDriver


_SETTINGS_RE = re.compile(r"^Settings for (?P<iface>eth\d+(?:\.\d+)?):$", re.IGNORECASE)
_VIF_BLOCK_RE = re.compile(r"vif\s+(?P<vlan>\d+)\s*\{(?P<body>.*?)^\s*\}", re.IGNORECASE | re.MULTILINE | re.DOTALL)
_SWITCH_NAME_RE = re.compile(r"^set interfaces switch (?P<switch>\S+)\b", re.IGNORECASE)
_DESC_RE = re.compile(r"^set interfaces ethernet (?P<iface>eth\d+) description (?P<value>.+)$", re.IGNORECASE)
_DISABLE_RE = re.compile(r"^set interfaces ethernet (?P<iface>eth\d+) disable$", re.IGNORECASE)
_POE_RE = re.compile(r"^set interfaces ethernet (?P<iface>eth\d+) poe output (?P<value>\S+)$", re.IGNORECASE)
_ETH_VIF_RE = re.compile(r"^set interfaces ethernet (?P<iface>eth\d+) vif (?P<vlan>\d+)(?:\b|$)", re.IGNORECASE)
_SWITCH_PORT_RE = re.compile(r"^set interfaces switch (?P<switch>\S+) switch-port interface (?P<iface>eth\d+)(?:\b|$)", re.IGNORECASE)
_SWITCH_PORT_PVID_RE = re.compile(
    r"^set interfaces switch (?P<switch>\S+) switch-port interface (?P<iface>eth\d+) vlan pvid (?P<vlan>\d+)$",
    re.IGNORECASE,
)
_SWITCH_PORT_VID_RE = re.compile(
    r"^set interfaces switch (?P<switch>\S+) switch-port interface (?P<iface>eth\d+) vlan vid (?P<vlan>\d+)$",
    re.IGNORECASE,
)
_ARP_RE = re.compile(
    r"^(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?:\S+\s+)?(?P<mac>(?:[0-9a-f]{2}:){5}[0-9a-f]{2}|\(incomplete\))\s+\S*\s*(?P<iface>\S+)$",
    re.IGNORECASE,
)


def _clean_edgeos_output(output: str) -> str:
    cleaned = output.replace("\r", "")
    cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", cleaned)
    return cleaned.strip()


def _parse_edgeos_config_state(output: str) -> dict[str, dict]:
    state: dict[str, dict] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = _SWITCH_PORT_PVID_RE.match(line)
        if match:
            iface = match.group("iface")
            entry = state.setdefault(iface, {})
            entry["port_profile"] = "switch-port"
            entry["switch_name"] = match.group("switch")
            entry["native_vlan_id"] = int(match.group("vlan"))
            continue

        match = _SWITCH_PORT_VID_RE.match(line)
        if match:
            iface = match.group("iface")
            entry = state.setdefault(iface, {})
            entry["port_profile"] = "switch-port"
            entry["switch_name"] = match.group("switch")
            entry.setdefault("tagged_vlans", set()).add(int(match.group("vlan")))
            continue

        match = _DESC_RE.match(line)
        if match:
            iface = match.group("iface")
            state.setdefault(iface, {})["alias"] = match.group("value").strip().strip("'\"")
            continue

        match = _DISABLE_RE.match(line)
        if match:
            iface = match.group("iface")
            state.setdefault(iface, {})["admin_enabled"] = False
            continue

        match = _POE_RE.match(line)
        if match:
            iface = match.group("iface")
            state.setdefault(iface, {})["poe_enabled"] = match.group("value").strip().lower() != "off"
            continue

        match = _ETH_VIF_RE.match(line)
        if match:
            iface = match.group("iface")
            entry = state.setdefault(iface, {})
            entry.setdefault("vif_vlans", set()).add(int(match.group("vlan")))
            continue

        match = _SWITCH_PORT_RE.match(line)
        if match:
            iface = match.group("iface")
            entry = state.setdefault(iface, {})
            entry["port_profile"] = "switch-port"
            entry["switch_name"] = match.group("switch")

    for entry in state.values():
        native_vlan = entry.get("native_vlan_id")
        tagged_vlans = sorted(int(vlan) for vlan in entry.pop("tagged_vlans", set()))
        vif_vlans = sorted(int(vlan) for vlan in entry.pop("vif_vlans", set()))
        if native_vlan is not None:
            tagged_vlans = [vlan for vlan in tagged_vlans if vlan != native_vlan]

        entry["tagged_vlans"] = tagged_vlans
        entry["vif_vlans"] = vif_vlans
        entry["has_l3_vifs"] = bool(vif_vlans)
        entry["switch_name"] = entry.get("switch_name") or ""
        entry["port_profile"] = entry.get("port_profile") or "routed"

        if entry["port_profile"] == "switch-port":
            if native_vlan is not None:
                entry["vlan_id"] = native_vlan
                entry["vlan_mode"] = "untagged"
            elif tagged_vlans:
                entry["vlan_id"] = tagged_vlans[0]
                entry["vlan_mode"] = "tagged"

    return state


def _parse_edgeos_interfaces(output: str, config_state: dict[str, dict] | None = None) -> list[dict]:
    rows: list[dict] = []
    current: dict | None = None
    config_state = config_state or {}

    def flush() -> None:
        nonlocal current
        if not current:
            return

        iface = str(current["iface"])
        config = config_state.get(iface, {})
        current = None
        if "." in iface:
            return

        rows.append({
            "port_number": int(iface.removeprefix("eth")) + 1,
            "link_state": current_link,
            "admin_enabled": bool(config.get("admin_enabled", True)),
            "speed": current_speed,
            "duplex": current_duplex,
            "poe_enabled": bool(config.get("poe_enabled", False)),
            "alias": str(config.get("alias", "")).strip(),
            "switch_name": str(config.get("switch_name", "")).strip(),
            "port_profile": str(config.get("port_profile", "routed")).strip(),
            "tagged_vlans": list(config.get("tagged_vlans", [])),
            "vif_vlans": list(config.get("vif_vlans", [])),
            "has_l3_vifs": bool(config.get("has_l3_vifs", False)),
            "native_vlan_id": config.get("native_vlan_id"),
            "vlan_id": config.get("vlan_id"),
            "vlan_mode": config.get("vlan_mode"),
        })

    current_link = "down"
    current_speed = None
    current_duplex = None
    for line in output.splitlines():
        stripped = line.strip()
        match = _SETTINGS_RE.match(stripped)
        if match:
            flush()
            current = {"iface": match.group("iface")}
            current_link = "down"
            current_speed = None
            current_duplex = None
            continue

        if not current or not stripped:
            continue

        lowered = stripped.lower()
        if lowered.startswith("speed:"):
            current_speed = stripped.split(":", 1)[1].strip().replace(" ", "")
        elif lowered.startswith("duplex:"):
            current_duplex = stripped.split(":", 1)[1].strip().lower()
        elif lowered.startswith("link detected:"):
            current_link = "up" if stripped.split(":", 1)[1].strip().lower() == "yes" else "down"

    flush()
    return rows


def _parse_edgeos_vlans(output: str) -> list[dict]:
    rows: list[dict] = []
    for match in _VIF_BLOCK_RE.finditer(output):
        vlan_id = int(match.group("vlan"))
        body = match.group("body")
        description_match = re.search(r"^\s*description\s+(?P<value>.+)$", body, re.IGNORECASE | re.MULTILINE)
        address_match = re.search(r"^\s*address\s+(?P<value>\S+)$", body, re.IGNORECASE | re.MULTILINE)
        rows.append({
            "vlan_id": vlan_id,
            "name": description_match.group("value").strip().strip('"') if description_match else f"VLAN{vlan_id}",
            "address": address_match.group("value").strip() if address_match else "",
        })
    return rows


def _switches_from_config(output: str) -> list[str]:
    switches = {
        match.group("switch")
        for line in output.splitlines()
        if (match := _SWITCH_NAME_RE.match(line.strip()))
    }
    return sorted(switches)


def _parse_edgeos_arp_table(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("address"):
            continue

        columns = re.split(r"\s{2,}|\s+", stripped)
        if len(columns) < 4 or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", columns[0]):
            continue

        iface = columns[-1]
        mac = columns[2].lower() if len(columns) >= 5 else columns[1].lower()
        status = "complete" if mac != "(incomplete)" else "incomplete"
        rows.append({
            "ip": columns[0],
            "mac": mac,
            "interface": iface,
            "status": status,
        })
    return rows


def _parse_edgeos_interface_metrics(output: str, config_state: dict[str, dict] | None = None) -> list[dict]:
    config_state = config_state or {}
    rows: list[dict] = []
    blocks = re.split(r"(?=^[A-Za-z0-9.@_-]+:)", output, flags=re.MULTILINE)
    for block in blocks:
        stripped = block.strip()
        if not stripped:
            continue

        header_line = stripped.splitlines()[0]
        iface = header_line.split(":", 1)[0].split("@", 1)[0].strip()
        config = config_state.get(iface, {})
        rx_match = re.search(
            r"RX:\s+bytes\s+packets\s+errors\s+dropped.*?\n\s*(?P<bytes>\d+)\s+(?P<packets>\d+)\s+(?P<errors>\d+)\s+(?P<dropped>\d+)",
            stripped,
            re.IGNORECASE | re.DOTALL,
        )
        tx_match = re.search(
            r"TX:\s+bytes\s+packets\s+errors\s+dropped.*?\n\s*(?P<bytes>\d+)\s+(?P<packets>\d+)\s+(?P<errors>\d+)\s+(?P<dropped>\d+)",
            stripped,
            re.IGNORECASE | re.DOTALL,
        )
        desc_match = re.search(r"^\s*Description:\s*(?P<value>.+)$", stripped, re.IGNORECASE | re.MULTILINE)
        inet_match = re.search(r"^\s*inet\s+(?P<value>\S+)", stripped, re.IGNORECASE | re.MULTILINE)
        link_state = "up" if "LOWER_UP" in header_line else "down"

        port_number = None
        if iface.startswith("eth") and "." not in iface:
            try:
                port_number = int(iface.removeprefix("eth")) + 1
            except ValueError:
                port_number = None

        rows.append({
            "name": iface,
            "port_number": port_number,
            "description": (desc_match.group("value").strip() if desc_match else str(config.get("alias", "")).strip()),
            "address": inet_match.group("value").strip() if inet_match else "",
            "link_state": link_state,
            "rx_bytes": int(rx_match.group("bytes")) if rx_match else 0,
            "rx_packets": int(rx_match.group("packets")) if rx_match else 0,
            "rx_errors": int(rx_match.group("errors")) if rx_match else 0,
            "rx_dropped": int(rx_match.group("dropped")) if rx_match else 0,
            "tx_bytes": int(tx_match.group("bytes")) if tx_match else 0,
            "tx_packets": int(tx_match.group("packets")) if tx_match else 0,
            "tx_errors": int(tx_match.group("errors")) if tx_match else 0,
            "tx_dropped": int(tx_match.group("dropped")) if tx_match else 0,
        })
    return rows


def _parse_edgeos_routes(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Codes:") or stripped.startswith("IP Route Table"):
            continue
        if not re.match(r"^[A-Z]", stripped):
            continue

        parts = stripped.split()
        if len(parts) < 2:
            continue

        protocol = parts[0]
        selected = ">" in protocol
        fib = "*" in protocol
        prefix = parts[1]
        next_hop = ""
        interface = ""
        if "via" in parts:
            via_index = parts.index("via")
            if via_index + 1 < len(parts):
                next_hop = parts[via_index + 1].rstrip(",")
            if via_index + 2 < len(parts):
                interface = parts[via_index + 2].rstrip(",")
        elif "connected," in stripped and "," in stripped:
            interface = stripped.rsplit(",", 1)[-1].strip()

        rows.append({
            "protocol": protocol.replace(">", "").replace("*", ""),
            "selected": selected,
            "fib": fib,
            "prefix": prefix,
            "next_hop": next_hop,
            "interface": interface,
            "raw": stripped,
        })
    return rows


def _parse_edgeos_dhcp_leases(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("ip address") or stripped.lower().startswith("----------"):
            continue

        columns = re.split(r"\s{2,}", stripped)
        if len(columns) < 4 or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", columns[0]):
            continue

        rows.append({
            "ip": columns[0],
            "mac": columns[1].lower(),
            "lease_expires": columns[2],
            "pool": columns[3],
            "client_name": columns[4] if len(columns) > 4 else "",
        })
    return rows


def _parse_edgeos_offload_status(output: str) -> dict:
    export_match = re.search(r"export\s*:\s*(?P<value>\w+)", output, re.IGNORECASE)
    dpi_match = re.search(r"dpi\s*:\s*(?P<value>\w+)", output, re.IGNORECASE)
    return {
        "traffic_export": export_match.group("value").lower() if export_match else "unknown",
        "dpi": dpi_match.group("value").lower() if dpi_match else "unknown",
        "raw": output,
    }


class EdgeOSSSHDriver(SwitchDriver):
    """Treiber für Ubiquiti EdgeRouter/EdgeOS via vyatta/vbash CLI."""

    def __init__(self, host: str, port: int, username: str, password: str | None, key_path: str | None, model_hint: str | None = None):
        self.ssh = SSHClientService(host, port, username, password, key_path)
        self.model_hint = model_hint or ""

    def connect(self) -> None:
        self.ssh.connect()

    def close(self) -> None:
        self.ssh.close()

    def _iface(self, port: int) -> str:
        return f"eth{max(0, port - 1)}"

    def _wrap_vbash(self, commands: list[str]) -> str:
        script = ["source /opt/vyatta/etc/functions/script-template", *commands]
        return "vbash -ic \"" + "; ".join(script).replace('"', '\\"') + "\""

    def _run_show(self, command: str) -> str:
        return self.ssh.execute_command(self._wrap_vbash([command]))

    def _run_config_commands(self, commands: list[str], dry_run: bool = True) -> dict:
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}

        shell_commands = ["source /opt/vyatta/etc/functions/script-template", "configure", *commands, "commit", "save"]
        output = [_clean_edgeos_output(chunk) for chunk in self.ssh.execute_config_commands(shell_commands)]
        joined = "\n".join(chunk for chunk in output if chunk).lower()
        for marker in (
            "commit failed",
            "configuration error",
            "invalid command",
            "not valid",
            "permission denied",
            "without config session",
            "failed to generate committed config",
            "set failed",
            "delete failed",
        ):
            if marker in joined:
                raise SSHExecutionError("\n".join(chunk for chunk in output if chunk) or "EdgeOS-Konfiguration fehlgeschlagen")
        return {"dry_run": False, "commands": commands, "output": output}

    def _get_config_state(self) -> dict[str, dict]:
        return _parse_edgeos_config_state(self._run_show("show configuration commands"))

    def get_config_commands(self) -> str:
        return self._run_show("show configuration commands")

    def list_switches(self) -> list[str]:
        return _switches_from_config(self._run_show("show configuration commands"))

    def _default_switch_name(self, config_output: str | None = None) -> str | None:
        output = config_output if config_output is not None else self._run_show("show configuration commands")
        switches = _switches_from_config(output)
        if "switch0" in switches:
            return "switch0"
        return switches[0] if switches else None

    def _port_switch_name(self, iface: str) -> str | None:
        return self._get_config_state().get(iface, {}).get("switch_name")

    def supports_poe_port(self, port: int) -> bool:
        return port == 5

    def poe_support_reason(self, port: int) -> str:
        iface = self._iface(port)
        if port == 1:
            return (
                f"{iface} ist beim EdgeRouter X der PoE-In-Port. "
                "Darueber wird der Router selbst mit 24V passivem PoE versorgt; das ist keine schaltbare PoE-Out-Funktion."
            )
        if port == 5:
            return ""
        return (
            f"Auf diesem EdgeOS-Geraet ist fuer {iface} kein schaltbarer PoE-Port vorhanden."
        )

    def poe_role_for_port(self, port: int) -> str:
        if port == 1:
            return "input"
        if port == 5:
            return "output"
        return "none"

    def poe_note_for_port(self, port: int) -> str:
        if port == 1:
            return "PoE In: versorgt den Router selbst mit 24V passivem PoE. Nicht per WebUI ein- oder ausschaltbar."
        if port == 5:
            return (
                "PoE Out: passives 24V-Passthrough auf eth4. Funktioniert nur mit passender Eingangsstromquelle "
                "und kann je nach aktueller Stromversorgung vom Geraet mit `24v is not supported` abgelehnt werden."
            )
        return ""

    def configure_switch_port(
        self,
        port: int,
        *,
        profile: str,
        native_vlan: int | None,
        tagged_vlans: list[int] | None = None,
        switch_name: str | None = None,
        remove_l3_vifs: bool = False,
        dry_run: bool = True,
    ) -> dict:
        iface = self._iface(port)
        tagged = sorted({int(vlan) for vlan in (tagged_vlans or []) if int(vlan) > 0})

        if native_vlan is not None:
            native_vlan = int(native_vlan)
            tagged = [vlan for vlan in tagged if vlan != native_vlan]

        config_output = self._run_show("show configuration commands")
        config_state = _parse_edgeos_config_state(config_output)
        current = config_state.get(iface, {})
        current_profile = current.get("port_profile", "routed")
        current_switch = current.get("switch_name") or ""
        current_native = current.get("vlan_id")
        current_tagged = sorted(int(vlan) for vlan in current.get("tagged_vlans", []))
        current_vifs = sorted(int(vlan) for vlan in current.get("vif_vlans", []))

        desired_profile = "switch-port" if profile == "switch-port" else "routed"
        desired_switch = switch_name or current_switch or self._default_switch_name(config_output)
        if desired_profile == "switch-port" and not desired_switch:
            raise RuntimeError("Kein EdgeOS-Switch-Interface gefunden. Bitte zuerst ein Switch-Interface wie switch0 anlegen.")
        if desired_profile == "switch-port" and current_vifs and not remove_l3_vifs:
            vlan_list = ", ".join(str(vlan) for vlan in current_vifs)
            raise RuntimeError(
                f"{iface} hat noch Layer-3-VIFs ({vlan_list}). "
                "Ein EdgeOS-Switch-Port darf keine VIFs besitzen. "
                "Entferne die VIFs zuerst oder aktiviere in der WebUI die Option zum Entfernen der Layer-3-VIFs."
            )

        if desired_profile == "routed":
            if current_profile == "routed":
                return {"dry_run": dry_run, "commands": [], "output": ["Port bereits als Routed Ethernet konfiguriert."] if not dry_run else []}
            commands = [f"delete interfaces switch {current_switch or desired_switch} switch-port interface {iface}"]
            return self._run_config_commands(commands, dry_run)

        desired_native = native_vlan if native_vlan is not None else None
        if desired_native is None and not tagged:
            desired_native = 1

        if (
            current_profile == "switch-port"
            and current_switch == desired_switch
            and current_native == desired_native
            and current_tagged == tagged
        ):
            return {"dry_run": dry_run, "commands": [], "output": ["Switch-Port bereits aktuell."] if not dry_run else []}

        commands: list[str] = []
        if desired_profile == "switch-port" and remove_l3_vifs:
            for vlan in current_vifs:
                commands.append(f"delete interfaces ethernet {iface} vif {vlan}")
        if current_switch and current_switch != desired_switch:
            commands.append(f"delete interfaces switch {current_switch} switch-port interface {iface}")
        commands.append(f"delete interfaces switch {desired_switch} switch-port interface {iface}")
        commands.append(f"set interfaces switch {desired_switch} switch-port interface {iface}")
        if desired_native is not None:
            commands.append(f"set interfaces switch {desired_switch} switch-port interface {iface} vlan pvid {desired_native}")
        for vlan in tagged:
            commands.append(f"set interfaces switch {desired_switch} switch-port interface {iface} vlan vid {vlan}")
        return self._run_config_commands(commands, dry_run)

    def get_system_info(self) -> dict:
        cmd = "show version"
        output = self._run_show(cmd)
        model_match = re.search(r"^HW model:\s*(?P<value>.+)$", output, re.IGNORECASE | re.MULTILINE)
        version_match = re.search(r"^Version:\s*(?P<value>.+)$", output, re.IGNORECASE | re.MULTILINE)
        return {
            "raw": output,
            "command": cmd,
            "model": model_match.group("value").strip() if model_match else None,
            "firmware": version_match.group("value").strip() if version_match else None,
        }

    def get_interfaces(self) -> list[dict]:
        cmd = "show interfaces ethernet physical"
        output = self._run_show(cmd)
        rows = _parse_edgeos_interfaces(output, self._get_config_state())
        for row in rows:
            port_number = int(row.get("port_number", 0) or 0)
            row["poe_supported"] = self.supports_poe_port(port_number)
            row["poe_reason"] = self.poe_support_reason(port_number) if not row["poe_supported"] else ""
            row["poe_role"] = self.poe_role_for_port(port_number)
            row["poe_note"] = self.poe_note_for_port(port_number)
        if rows:
            return rows
        return [{"raw": output, "command": cmd}]

    def get_vlans(self) -> list[dict]:
        cmd = "show configuration"
        output = self._run_show(cmd)
        rows = _parse_edgeos_vlans(output)
        if rows:
            return rows
        return [{"raw": output, "command": cmd}]

    def get_arp_table(self) -> list[dict]:
        output = self._run_show("show arp")
        rows = _parse_edgeos_arp_table(output)
        if rows:
            return rows
        return [{"raw": output, "command": "show arp"}]

    def get_interface_metrics(self) -> list[dict]:
        output = self._run_show("show interfaces detail")
        rows = _parse_edgeos_interface_metrics(output, self._get_config_state())
        if rows:
            return rows
        return [{"raw": output, "command": "show interfaces detail"}]

    def get_routes(self) -> list[dict]:
        output = self._run_show("show ip route")
        rows = _parse_edgeos_routes(output)
        if rows:
            return rows
        return [{"raw": output, "command": "show ip route"}]

    def get_dhcp_leases(self) -> list[dict]:
        output = self._run_show("show dhcp leases")
        rows = _parse_edgeos_dhcp_leases(output)
        if rows:
            return rows
        return [{"raw": output, "command": "show dhcp leases"}]

    def get_offload_status(self) -> dict:
        output = self._run_show("show ubnt offload")
        return _parse_edgeos_offload_status(output)

    def create_vlan(self, vlan_id: int, name: str, dry_run: bool = True) -> dict:
        return self._run_config_commands([f"set interfaces ethernet eth0 vif {vlan_id} description '{name}'"], dry_run)

    def delete_vlan(self, vlan_id: int, dry_run: bool = True) -> dict:
        return self._run_config_commands([f"delete interfaces ethernet eth0 vif {vlan_id}"], dry_run)

    def assign_port_to_vlan(self, port: int, vlan_id: int, mode: str, dry_run: bool = True) -> dict:
        if mode == "excluded":
            return self.configure_switch_port(port, profile="routed", native_vlan=None, tagged_vlans=[], dry_run=dry_run)
        if mode == "tagged":
            return self.configure_switch_port(port, profile="switch-port", native_vlan=None, tagged_vlans=[vlan_id], dry_run=dry_run)
        return self.configure_switch_port(port, profile="switch-port", native_vlan=vlan_id, tagged_vlans=[], dry_run=dry_run)

    def set_port_alias(self, port: int, alias: str, dry_run: bool = True) -> dict:
        iface = self._iface(port)
        normalized = alias.strip()
        if not dry_run:
            current_alias = str(self._get_config_state().get(iface, {}).get("alias", "")).strip()
            if current_alias == normalized:
                return {"dry_run": False, "commands": [], "output": ["Alias bereits aktuell."]}
        if normalized:
            commands = [f"set interfaces ethernet {iface} description '{normalized}'"]
        else:
            commands = [f"delete interfaces ethernet {iface} description"]
        return self._run_config_commands(commands, dry_run)

    def set_port_admin_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        iface = self._iface(port)
        cmd = f"delete interfaces ethernet {iface} disable" if enabled else f"set interfaces ethernet {iface} disable"
        return self._run_config_commands([cmd], dry_run)

    def set_poe_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        iface = self._iface(port)
        if enabled and not self.supports_poe_port(port):
            raise RuntimeError(self.poe_support_reason(port))
        cmd = f"set interfaces ethernet {iface} poe output 24v" if enabled else f"delete interfaces ethernet {iface} poe"
        try:
            return self._run_config_commands([cmd], dry_run)
        except SSHExecutionError as exc:
            message = str(exc)
            if "24v is not supported" in message.lower():
                raise RuntimeError(
                    f"{iface} ist zwar der PoE-Out-Port des EdgeRouter X, aber in deinem aktuellen Setup steht dort kein nutzbares 24V-Passthrough zur Verfuegung. "
                    "Das ist meist der Fall, wenn der Router nicht ueber passenden 24V-PoE-In oder keine ausreichend starke Eingangsstromquelle versorgt wird."
                ) from exc
            raise

    def reboot_device(self, dry_run: bool = True) -> dict:
        if dry_run:
            return {"dry_run": True, "commands": ["reboot"], "output": []}
        output = self.ssh.execute_command("sudo reboot")
        return {"dry_run": False, "commands": ["sudo reboot"], "output": [output]}

    def backup_config(self, dry_run: bool = True) -> dict:
        if dry_run:
            return {"dry_run": True, "commands": ["show configuration"], "output": []}
        output = self._run_show("show configuration")
        return {"dry_run": False, "commands": ["show configuration"], "output": [output]}

    def save_config(self, dry_run: bool = True) -> dict:
        return self._run_config_commands([], dry_run)

    def execute_expert_commands(self, commands: list[str], dry_run: bool = True) -> dict:
        normalized: list[str] = []
        for command in commands:
            stripped = command.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower() in {"configure", "commit", "save", "exit"}:
                continue
            normalized.append(stripped)

        if not normalized:
            return {
                "dry_run": dry_run,
                "commands": [],
                "output": ["Keine EdgeOS-Befehle uebergeben."] if not dry_run else [],
            }

        return self._run_config_commands(normalized, dry_run)
