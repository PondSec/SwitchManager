from __future__ import annotations

from .command_builder import CommandAction, CommandBuilder
from .ssh_client import SSHClientService
from .switch_driver_base import SwitchDriver


class ZyxelSSHDriver(SwitchDriver):
    """Driver mit generischer Struktur. CLI-Syntax pro Modell prüfen und in build_* Methoden anpassen."""

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

    def get_system_info(self) -> dict:
        # TODO: Reale CLI-Syntax je nach Zyxel-Modell verifizieren (z.B. GS-Serie show system-information).
        cmd = "show system-information"
        return {"raw": self.ssh.execute_command(cmd), "command": cmd}

    def get_interfaces(self) -> list[dict]:
        # TODO: Reale CLI-Syntax und Parsing für Interfaces pro Modell ergänzen.
        cmd = "show interfaces status"
        output = self.ssh.execute_command(cmd)
        return [{"raw": output, "command": cmd}]

    def get_vlans(self) -> list[dict]:
        # TODO: Reale CLI-Syntax und Parsing pro Modell ergänzen.
        cmd = "show vlan"
        output = self.ssh.execute_command(cmd)
        return [{"raw": output, "command": cmd}]

    def create_vlan(self, vlan_id: int, name: str, dry_run: bool = True) -> dict:
        cmds = CommandBuilder.build(CommandAction("create_vlan", {"vlan_id": vlan_id, "name": name}))
        return self._run(cmds, dry_run)

    def delete_vlan(self, vlan_id: int, dry_run: bool = True) -> dict:
        # TODO: Reale Zyxel-CLI für VLAN-Löschung prüfen.
        return self._run([f"no vlan {vlan_id}"], dry_run)

    def assign_port_to_vlan(self, port: int, vlan_id: int, mode: str, dry_run: bool = True) -> dict:
        cmds = CommandBuilder.build(CommandAction("assign_port_vlan", {"port": port, "vlan_id": vlan_id, "mode": mode}))
        return self._run(cmds, dry_run)

    def set_port_admin_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        cmds = CommandBuilder.build(CommandAction("set_port_admin_state", {"port": port, "enabled": enabled}))
        return self._run(cmds, dry_run)

    def set_poe_state(self, port: int, enabled: bool, dry_run: bool = True) -> dict:
        cmds = CommandBuilder.build(CommandAction("set_poe_state", {"port": port, "enabled": enabled}))
        return self._run(cmds, dry_run)

    def reboot_device(self, dry_run: bool = True) -> dict:
        # TODO: Reale Zyxel-CLI für Reboot prüfen.
        return self._run(["reload"], dry_run)

    def backup_config(self, dry_run: bool = True) -> dict:
        # TODO: Reale Zyxel-CLI/API für Konfig-Backup prüfen.
        return self._run(["show running-config"], dry_run)

    def save_config(self, dry_run: bool = True) -> dict:
        # TODO: Reale Zyxel-CLI für Save prüfen (z.B. write memory).
        return self._run(["write memory"], dry_run)
