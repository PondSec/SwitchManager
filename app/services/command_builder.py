from dataclasses import dataclass


class CommandBuildError(ValueError):
    pass


@dataclass
class CommandAction:
    name: str
    params: dict


class CommandBuilder:
    @staticmethod
    def build(action: CommandAction) -> list[str]:
        if action.name == "create_vlan":
            vlan_id = int(action.params["vlan_id"])
            name = action.params["name"].strip()
            if vlan_id < 1 or vlan_id > 4094:
                raise CommandBuildError("VLAN-ID ungültig")
            if not name or len(name) > 120:
                raise CommandBuildError("VLAN-Name ungültig")
            return [f"vlan {vlan_id}", f"name {name}"]

        if action.name == "set_port_admin_state":
            port = int(action.params["port"])
            enabled = bool(action.params["enabled"])
            if port < 1 or port > 48:
                raise CommandBuildError("Port ungültig")
            return [f"interface ethernet {port}", "no shutdown" if enabled else "shutdown"]

        if action.name == "assign_port_vlan":
            port = int(action.params["port"])
            vlan_id = int(action.params["vlan_id"])
            mode = action.params["mode"]
            if mode not in {"tagged", "untagged", "excluded"}:
                raise CommandBuildError("VLAN-Modus ungültig")
            return [f"interface ethernet {port}", f"switchport mode {mode}", f"switchport vlan {vlan_id}"]

        if action.name == "set_poe_state":
            port = int(action.params["port"])
            enabled = bool(action.params["enabled"])
            return [f"interface ethernet {port}", "poe enable" if enabled else "poe disable"]

        raise CommandBuildError(f"Nicht erlaubte Aktion: {action.name}")
