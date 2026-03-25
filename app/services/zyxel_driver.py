from __future__ import annotations

from .ssh_client import SSHClientService
from .switch_driver_base import SwitchDriver


class ZyxelSSHDriver(SwitchDriver):
    """CLI-Treiber für Zyxel GS-Serie (best-effort für GS1900/GS1920)."""

    def __init__(self, host: str, port: int, username: str, password: str | None, key_path: str | None):
        self.ssh = SSHClientService(host, port, username, password, key_path)

    def connect(self) -> None:
        self.ssh.connect()

    def close(self) -> None:
        self.ssh.close()

    def _run(self, commands: list[str], dry_run: bool = True) -> dict:
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}
        output = self.ssh.execute_config_commands(commands)
        return {"dry_run": False, "commands": commands, "output": output}

    def _first_success(self, commands: list[str]) -> tuple[str, str]:
        last_error: Exception | None = None
        for cmd in commands:
            try:
                return cmd, self.ssh.execute_command(cmd)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("Kein Kommando verfügbar")

    def get_system_info(self) -> dict:
        cmd, output = self._first_success([
            "show system-information",
            "show system",
            "show version",
        ])
        return {"raw": output, "command": cmd}

    def get_interfaces(self) -> list[dict]:
        cmd, output = self._first_success([
            "show interfaces status",
            "show interfaces",
            "show interface status",
        ])
        return [{"raw": output, "command": cmd}]

    def get_vlans(self) -> list[dict]:
        cmd, output = self._first_success([
            "show vlan",
            "show vlan all",
        ])
        return [{"raw": output, "command": cmd}]

    def create_vlan(self, vlan_id: int, name: str, dry_run: bool = True) -> dict:
        cmds = ["configure terminal", f"vlan {vlan_id}", f"name {name}", "exit", "exit", "write memory"]
        return self._run(cmds, dry_run)

    def delete_vlan(self, vlan_id: int, dry_run: bool = True) -> dict:
        cmds = ["configure terminal", f"no vlan {vlan_id}", "exit", "write memory"]
        return self._run(cmds, dry_run)

    def assign_port_to_vlan(self, port: int, vlan_id: int, mode: str, dry_run: bool = True) -> dict:
        if mode == "tagged":
            switchport_cmd = f"switchport trunk allowed vlan add {vlan_id}"
        elif mode == "excluded":
            switchport_cmd = f"switchport trunk allowed vlan remove {vlan_id}"
        else:
            switchport_cmd = f"switchport access vlan {vlan_id}"

        cmds = [
            "configure terminal",
            f"interface gigabit-ethernet 1/{port}",
            switchport_cmd,
            "exit",
            "exit",
            "write memory",
        ]
        return self._run(cmds, dry_run)

    def set_port_admin_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        cmds = [
            "configure terminal",
            f"interface gigabit-ethernet 1/{port}",
            "no shutdown" if enabled else "shutdown",
            "exit",
            "exit",
            "write memory",
        ]
        return self._run(cmds, dry_run)

    def set_poe_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        cmds = [
            "configure terminal",
            f"interface gigabit-ethernet 1/{port}",
            "poe enable" if enabled else "no poe enable",
            "exit",
            "exit",
            "write memory",
        ]
        return self._run(cmds, dry_run)

    def reboot_device(self, dry_run: bool = True) -> dict:
        return self._run(["reload"], dry_run)

    def backup_config(self, dry_run: bool = True) -> dict:
        return self._run(["show running-config"], dry_run)

    def save_config(self, dry_run: bool = True) -> dict:
        return self._run(["write memory"], dry_run)
