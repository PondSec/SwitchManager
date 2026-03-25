from __future__ import annotations

import re
import time

from .ssh_client import SSHClientService
from .switch_driver_base import SwitchDriver
from .zyxel_web_config import ZyxelWebConfigClient


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PROMPT_RE = re.compile(r"(?m)(?:^|\n)[A-Za-z0-9._-]+(?:\([^)]+\))?[#>] ?$")
_ERROR_TOKENS = (
    "unknown command",
    "incomplete command",
    "invalid port id",
    "invalid input",
    "permission denied",
    "access denied",
)


def _parse_zyxel_interfaces(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("port ") or stripped.startswith("-"):
            continue

        columns = re.split(r"\s{2,}", stripped)
        if not columns or not columns[0].isdigit():
            continue

        port_number = int(columns[0])
        state_index = 1
        alias = ""
        if len(columns) >= 7:
            alias = columns[1].strip()
            state_index = 2
        elif len(columns) >= 6 and columns[1].strip().lower() not in {"connected", "connect", "notconnect", "not-connect", "up", "down", "disabled", "disable"}:
            alias = columns[1].strip()
            state_index = 2

        if len(columns) <= state_index + 3:
            continue

        state = columns[state_index].strip().lower().replace("-", "")
        vlan_token = columns[state_index + 1].strip()
        duplex_token = columns[state_index + 2].strip().lower()
        speed_token = columns[state_index + 3].strip()

        duplex = None if duplex_token == "auto" else duplex_token.removeprefix("a-")
        speed = None if speed_token.lower() == "auto" else speed_token.removeprefix("a-")
        rows.append({
            "port_number": port_number,
            "link_state": "up" if state in {"up", "connect", "connected"} else "down",
            "admin_enabled": state not in {"disabled", "disable"},
            "speed": speed,
            "duplex": duplex,
            "alias": alias,
            "vlan_id": int(vlan_token) if vlan_token.isdigit() else None,
        })
    return rows


def _parse_zyxel_vlans(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("vid") or stripped.startswith("-"):
            continue

        columns = [part.strip() for part in stripped.split("|")]
        if len(columns) < 5 or not columns[0].isdigit():
            continue

        rows.append({
            "vlan_id": int(columns[0]),
            "name": columns[1] or f"VLAN{columns[0]}",
            "untagged_ports": columns[2],
            "tagged_ports": columns[3],
            "membership_type": columns[4],
        })
    return rows


def _parse_zyxel_mac_table(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("vid") or stripped.startswith("-") or stripped.lower().startswith("total number"):
            continue

        columns = [part.strip() for part in stripped.split("|")]
        if len(columns) < 4 or not columns[0].isdigit():
            continue

        port_token = columns[3]
        port_number = int(port_token) if port_token.isdigit() else None
        rows.append({
            "vlan_id": int(columns[0]),
            "mac": columns[1].lower(),
            "entry_type": columns[2],
            "port": port_token,
            "port_number": port_number,
        })
    return rows


def _parse_zyxel_arp_table(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("address"):
            continue

        columns = re.split(r"\s{2,}", stripped)
        if len(columns) < 5:
            continue

        ip_address = columns[0].strip()
        mac = columns[2].strip().lower()
        if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip_address):
            continue

        rows.append({
            "ip": ip_address,
            "mac": mac,
            "interface": columns[4].strip(),
            "status": columns[3].strip(),
        })
    return rows


def _parse_zyxel_lldp_neighbors(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("port") or stripped.startswith("-"):
            continue

        columns = [part.strip() for part in stripped.split("|")]
        if len(columns) < 6 or not columns[0].isdigit():
            continue

        rows.append({
            "port_number": int(columns[0]),
            "device_id": columns[1],
            "remote_port_id": columns[2],
            "sys_name": columns[3],
            "capabilities": columns[4],
            "ttl": columns[5],
        })
    return rows


def _parse_zyxel_interface_metrics(output: str, port_number: int) -> dict:
    link_match = re.search(r"^GigabitEthernet(?P<port>\d+)\s+is\s+(?P<link>up|down)$", output, re.IGNORECASE | re.MULTILINE)
    speed_match = re.search(r"(?P<duplex>Auto-duplex|Full-duplex|Half-duplex),\s+(?P<speed>Auto-speed|\d+\w*)", output, re.IGNORECASE)
    rx_match = re.search(r"(?P<packets>\d+)\s+packets input,\s+(?P<bytes>\d+)\s+bytes", output, re.IGNORECASE)
    tx_match = re.search(r"(?P<packets>\d+)\s+packets output,\s+(?P<bytes>\d+)\s+bytes", output, re.IGNORECASE)
    error_match = re.search(r"(?P<input_errors>\d+)\s+input errors", output, re.IGNORECASE)
    output_errors_match = re.search(r"(?P<output_errors>\d+)\s+output errors", output, re.IGNORECASE)

    duplex = None
    speed = None
    if speed_match:
        duplex_raw = speed_match.group("duplex").lower().replace("-duplex", "")
        speed_raw = speed_match.group("speed").lower().replace("-speed", "")
        duplex = None if duplex_raw == "auto" else duplex_raw
        speed = None if speed_raw == "auto" else speed_raw

    return {
        "name": f"port{port_number}",
        "port_number": port_number,
        "link_state": (link_match.group("link").lower() if link_match else "down"),
        "speed": speed,
        "duplex": duplex,
        "rx_packets": int(rx_match.group("packets")) if rx_match else 0,
        "rx_bytes": int(rx_match.group("bytes")) if rx_match else 0,
        "tx_packets": int(tx_match.group("packets")) if tx_match else 0,
        "tx_bytes": int(tx_match.group("bytes")) if tx_match else 0,
        "input_errors": int(error_match.group("input_errors")) if error_match else 0,
        "output_errors": int(output_errors_match.group("output_errors")) if output_errors_match else 0,
        "raw": output,
    }


class ZyxelSSHDriver(SwitchDriver):
    """CLI-Treiber für Zyxel GS-Serie (best-effort für GS1900/GS1920)."""

    def __init__(self, host: str, port: int, username: str, password: str | None, key_path: str | None, model_hint: str | None = None):
        self.ssh = SSHClientService(host, port, username, password, key_path)
        self.model_hint = (model_hint or "").lower()

    def connect(self) -> None:
        self.ssh.connect()

    def close(self) -> None:
        self.ssh.close()

    def _strip_control_sequences(self, text: str) -> str:
        cleaned = _ANSI_RE.sub("", text)
        cleaned = cleaned.replace("\r", "")
        cleaned = cleaned.replace("\x08", "")
        cleaned = cleaned.replace("--More--", "")
        return cleaned

    def _has_prompt(self, text: str) -> bool:
        return bool(_PROMPT_RE.search(text.rstrip()))

    def _read_until_prompt(self, channel, timeout: float = 8) -> str:
        deadline = time.monotonic() + timeout
        chunks: list[str] = []
        while time.monotonic() < deadline:
            if channel.recv_ready():
                data = channel.recv(65535).decode("utf-8", errors="replace")
                chunks.append(data)
                if "--More--" in data:
                    channel.send(" ")
                if self._has_prompt(self._strip_control_sequences("".join(chunks))):
                    return "".join(chunks)
            else:
                time.sleep(0.1)
        return "".join(chunks)

    def _prime_shell(self, channel) -> None:
        banner = self._strip_control_sequences(self._read_until_prompt(channel, timeout=6))
        if "Press <Enter> to continue..." in banner or not self._has_prompt(banner):
            channel.send("\n")
            self._read_until_prompt(channel, timeout=6)

    def _normalize_response(self, command: str, raw_output: str) -> str:
        cleaned = self._strip_control_sequences(raw_output)
        lines: list[str] = []
        skipped_echo = False
        for line in cleaned.splitlines():
            stripped = line.strip()
            if not stripped or "Press <Enter> to continue..." in stripped:
                continue
            if not skipped_echo and stripped == command.strip():
                skipped_echo = True
                continue
            if _PROMPT_RE.fullmatch(stripped):
                continue
            lines.append(line.rstrip())
        return "\n".join(lines).strip()

    def _raise_for_cli_error(self, output: str) -> None:
        lowered = output.lower()
        if any(token in lowered for token in _ERROR_TOKENS):
            raise RuntimeError(output)

    def _execute_shell_commands(self, commands: list[str], timeout: float = 10) -> list[str]:
        if not self.ssh.client:
            raise RuntimeError("SSH-Client nicht verbunden")

        channel = self.ssh.client.invoke_shell(term="vt100", width=200, height=200)
        try:
            self._prime_shell(channel)
            outputs: list[str] = []
            for command in commands:
                channel.send(command + "\n")
                raw_output = self._read_until_prompt(channel, timeout=timeout)
                output = self._normalize_response(command, raw_output)
                self._raise_for_cli_error(output)
                outputs.append(output)
            return outputs
        finally:
            channel.close()

    def _run(self, commands: list[str], dry_run: bool = True) -> dict:
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}
        output = self._execute_shell_commands(commands, timeout=12)
        return {"dry_run": False, "commands": commands, "output": output}

    def _first_success(self, commands: list[str]) -> tuple[str, str]:
        last_error: Exception | None = None
        for cmd in commands:
            try:
                output = self._execute_shell_commands([cmd], timeout=12)[0]
                if output:
                    return cmd, output
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("Kein Kommando verfügbar")

    def _port_range(self) -> str:
        for ports in (48, 24, 16, 8):
            if f"-{ports}" in self.model_hint:
                return f"1-{ports}"
        return "1-24"

    def _web_client(self) -> ZyxelWebConfigClient:
        return ZyxelWebConfigClient(self.ssh.host, self.ssh.username, self.ssh.password)

    def get_system_info(self) -> dict:
        outputs: list[str] = []
        commands: list[str] = []
        for cmd in ("show info", "show board", "show version"):
            try:
                output = self._execute_shell_commands([cmd], timeout=12)[0]
            except Exception:  # noqa: BLE001
                continue
            if output:
                outputs.append(output)
                commands.append(cmd)

        if not outputs:
            raise RuntimeError("Keine Systeminformationen vom Zyxel erhalten")

        raw = "\n\n".join(outputs)
        model_match = re.search(r"^\s*(GS\d{4}-[A-Za-z0-9]+)\s*$", raw, re.IGNORECASE | re.MULTILINE)
        firmware_match = re.search(r"^Firmware Version\s*:\s*(?P<value>.+)$", raw, re.IGNORECASE | re.MULTILINE)
        ip_match = re.search(r"^IP Address\s*:\s*(?P<value>\S+)", raw, re.IGNORECASE | re.MULTILINE)
        return {
            "raw": raw,
            "command": ", ".join(commands),
            "model": model_match.group(1).strip() if model_match else None,
            "firmware": firmware_match.group("value").strip() if firmware_match else None,
            "mgmt_ip": ip_match.group("value").strip() if ip_match else None,
        }

    def get_interfaces(self) -> list[dict]:
        port_range = self._port_range()
        candidates = list(dict.fromkeys([
            f"show interface {port_range} status",
            f"show interfaces {port_range} status",
            "show interface 1 status",
        ]))
        cmd, output = self._first_success(candidates)
        parsed = _parse_zyxel_interfaces(output)
        if parsed:
            return parsed
        return [{"raw": output, "command": cmd}]

    def get_vlans(self) -> list[dict]:
        cmd, output = self._first_success(["show vlan", "show vlan all"])
        parsed = _parse_zyxel_vlans(output)
        if parsed:
            return parsed
        return [{"raw": output, "command": cmd}]

    def get_mac_table(self) -> list[dict]:
        cmd, output = self._first_success(["show mac address-table"])
        parsed = _parse_zyxel_mac_table(output)
        if parsed:
            return parsed
        return [{"raw": output, "command": cmd}]

    def get_arp_table(self) -> list[dict]:
        cmd, output = self._first_success(["show arp"])
        parsed = _parse_zyxel_arp_table(output)
        if parsed:
            return parsed
        return [{"raw": output, "command": cmd}]

    def get_lldp_neighbors(self) -> list[dict]:
        cmd, output = self._first_success(["show lldp neighbor"])
        parsed = _parse_zyxel_lldp_neighbors(output)
        if parsed:
            return parsed
        return [{"raw": output, "command": cmd}]

    def get_interface_metrics(self, port_numbers: list[int] | None = None) -> list[dict]:
        requested = sorted({int(port) for port in (port_numbers or []) if int(port) > 0})
        if not requested:
            requested = list(range(1, int(self._port_range().split("-")[-1]) + 1))

        outputs = self._execute_shell_commands([f"show interfaces {port}" for port in requested], timeout=12)
        rows: list[dict] = []
        for port_number, output in zip(requested, outputs, strict=False):
            rows.append(_parse_zyxel_interface_metrics(output, port_number))
        return rows

    def create_vlan(self, vlan_id: int, name: str, dry_run: bool = True) -> dict:
        commands = [f"web:create-vlan id={vlan_id} name={name[:28]}"]
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}
        result = self._web_client().create_vlan(vlan_id, name, save=True)
        return {"dry_run": False, "commands": commands, "output": [str(result)]}

    def delete_vlan(self, vlan_id: int, dry_run: bool = True) -> dict:
        commands = [f"web:delete-vlan id={vlan_id}"]
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}
        result = self._web_client().delete_vlan(vlan_id, save=True)
        return {"dry_run": False, "commands": commands, "output": [str(result)]}

    def assign_port_to_vlan(self, port: int, vlan_id: int, mode: str, dry_run: bool = True) -> dict:
        commands = [f"web:set-port-vlan port={port} vlan={vlan_id} mode={mode}"]
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}
        result = self._web_client().set_simple_port_membership(port, vlan_id, mode, save=True)
        return {"dry_run": False, "commands": commands, "output": [str(result)]}

    def set_port_alias(self, port: int, alias: str, dry_run: bool = True) -> dict:
        commands = [f"web:set-port-alias port={port} alias={alias[:32]}"]
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}
        result = self._web_client().set_port_physical(port, alias=alias, save=True)
        return {"dry_run": False, "commands": commands, "output": [str(result)]}

    def set_port_admin_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        commands = [f"web:set-port-admin port={port} enabled={1 if enabled else 0}"]
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}
        result = self._web_client().set_port_physical(port, admin_enabled=enabled, save=True)
        return {"dry_run": False, "commands": commands, "output": [str(result)]}

    def set_poe_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        raise RuntimeError("Der GS1900-24E besitzt kein schaltbares PoE pro Port.")

    def reboot_device(self, dry_run: bool = True) -> dict:
        raise RuntimeError("Reboot ist für dieses Zyxel-Modell bisher nur über die native Wartungsoberfläche freigegeben.")

    def backup_config(self, dry_run: bool = True) -> dict:
        return self._run(["show running-config"], dry_run)

    def save_config(self, dry_run: bool = True) -> dict:
        commands = ["web:save-config"]
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}
        result = self._web_client().save_config()
        return {"dry_run": False, "commands": commands, "output": [str(result)]}

    def supports_poe_port(self, port: int) -> bool:
        return False

    def poe_support_reason(self, port: int) -> str:
        return "Der GS1900-24E stellt kein schaltbares PoE pro Port bereit."
