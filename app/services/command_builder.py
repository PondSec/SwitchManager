import re
from dataclasses import dataclass


class CommandBuildError(ValueError):
    pass


@dataclass
class CommandAction:
    name: str
    params: dict


def _safe_label(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise CommandBuildError(f"{field_name} ungültig")
    if not re.fullmatch(r"[A-Za-z0-9_.\- ]+", normalized):
        raise CommandBuildError(f"{field_name} enthält unerlaubte Zeichen")
    return normalized


class CommandBuilder:
    @staticmethod
    def build(action: CommandAction) -> list[str]:
        if action.name == "create_vlan":
            vlan_id = int(action.params["vlan_id"])
            name = _safe_label(action.params["name"], "VLAN-Name")
            if vlan_id < 1 or vlan_id > 4094:
                raise CommandBuildError("VLAN-ID ungültig")
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

        if action.name == "apply_network_profile":
            vlan_id = int(action.params["vlan_id"])
            if vlan_id < 1 or vlan_id > 4094:
                raise CommandBuildError("VLAN-ID ungültig")
            name = _safe_label(action.params["name"], "Profilname")
            commands = [
                f"vlan {vlan_id}",
                f"name {name}",
                f"interface vlan {vlan_id}",
                f"ip address {action.params['gateway_ip']} {action.params['subnet_mask']}",
            ]
            if action.params.get("dhcp_enabled"):
                commands.extend([
                    f"ip dhcp pool VLAN{vlan_id}",
                    f"network {action.params['gateway_ip']} {action.params['subnet_mask']}",
                    f"default-router {action.params['gateway_ip']}",
                ])
                if action.params.get("dhcp_start") and action.params.get("dhcp_end"):
                    commands.append(f"address range {action.params['dhcp_start']} {action.params['dhcp_end']}")
                if action.params.get("dns_primary"):
                    dns_line = action.params["dns_primary"]
                    if action.params.get("dns_secondary"):
                        dns_line += f" {action.params['dns_secondary']}"
                    commands.append(f"dns-server {dns_line}")
                commands.append(f"lease {int(action.params['dhcp_lease_time'])}")
            else:
                commands.append(f"no ip dhcp pool VLAN{vlan_id}")

            for feature, cmd in {
                "igmp_snooping": "ip igmp snooping",
                "dhcp_guarding": "ip dhcp snooping",
                "upnp_lan": "ip upnp enable",
                "multicast_dns": "mdns-sd gateway",
            }.items():
                commands.append(cmd if action.params.get(feature) else f"no {cmd}")
            return commands

        raise CommandBuildError(f"Nicht erlaubte Aktion: {action.name}")
