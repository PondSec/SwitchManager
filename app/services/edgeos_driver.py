from __future__ import annotations

import re

from .ssh_client import SSHClientService
from .switch_driver_base import SwitchDriver


class EdgeOSSSHDriver(SwitchDriver):
    """Treiber für Ubiquiti EdgeRouter/EdgeOS via vyatta/vbash CLI."""

    def __init__(self, host: str, port: int, username: str, password: str | None, key_path: str | None):
        self.ssh = SSHClientService(host, port, username, password, key_path)

    def connect(self) -> None:
        self.ssh.connect()

    def close(self) -> None:
        self.ssh.close()

    def _iface(self, port: int) -> str:
        return f"eth{max(0, port - 1)}"

    def _run_vbash(self, commands: list[str], dry_run: bool = True) -> dict:
        if dry_run:
            return {"dry_run": True, "commands": commands, "output": []}

        script = [
            "source /opt/vyatta/etc/functions/script-template",
            "configure",
            *commands,
            "commit",
            "save",
            "exit",
        ]
        wrapped = "vbash -ic \"" + "; ".join(script).replace('"', '\\"') + "\""
        output = self.ssh.execute_command(wrapped)
        return {"dry_run": False, "commands": commands, "output": [output]}

    def get_system_info(self) -> dict:
        cmd = "show version"
        return {"raw": self.ssh.execute_command(cmd), "command": cmd}

    def get_interfaces(self) -> list[dict]:
        cmd = "show interfaces ethernet physical"
        output = self.ssh.execute_command(cmd)
        rows: list[dict] = []
        pattern = re.compile(r"^(eth(?P<idx>\d+)).*?(?P<link>up|down)", re.IGNORECASE)
        for line in output.splitlines():
            match = pattern.search(line.strip())
            if not match:
                continue
            rows.append({
                "port_number": int(match.group("idx")) + 1,
                "link_state": match.group("link").lower(),
                "admin_enabled": True,
            })
        if rows:
            return rows
        return [{"raw": output, "command": cmd}]

    def get_vlans(self) -> list[dict]:
        cmd = "show configuration commands | match vlan"
        output = self.ssh.execute_command(cmd)
        return [{"raw": output, "command": cmd}]

    def create_vlan(self, vlan_id: int, name: str, dry_run: bool = True) -> dict:
        return self._run_vbash([f"set interfaces switch switch0 vif {vlan_id} description '{name}'"], dry_run)

    def delete_vlan(self, vlan_id: int, dry_run: bool = True) -> dict:
        return self._run_vbash([f"delete interfaces switch switch0 vif {vlan_id}"], dry_run)

    def assign_port_to_vlan(self, port: int, vlan_id: int, mode: str, dry_run: bool = True) -> dict:
        iface = self._iface(port)
        commands = [f"set interfaces ethernet {iface} description 'vlan-{vlan_id}-{mode}'"]
        return self._run_vbash(commands, dry_run)

    def set_port_admin_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        iface = self._iface(port)
        cmd = f"delete interfaces ethernet {iface} disable" if enabled else f"set interfaces ethernet {iface} disable"
        return self._run_vbash([cmd], dry_run)

    def set_poe_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        iface = self._iface(port)
        cmd = f"set interfaces ethernet {iface} poe output 24v" if enabled else f"delete interfaces ethernet {iface} poe"
        return self._run_vbash([cmd], dry_run)

    def reboot_device(self, dry_run: bool = True) -> dict:
        if dry_run:
            return {"dry_run": True, "commands": ["reboot"], "output": []}
        output = self.ssh.execute_command("sudo reboot")
        return {"dry_run": False, "commands": ["sudo reboot"], "output": [output]}

    def backup_config(self, dry_run: bool = True) -> dict:
        if dry_run:
            return {"dry_run": True, "commands": ["show configuration"], "output": []}
        output = self.ssh.execute_command("show configuration")
        return {"dry_run": False, "commands": ["show configuration"], "output": [output]}

    def save_config(self, dry_run: bool = True) -> dict:
        return self._run_vbash([], dry_run)
