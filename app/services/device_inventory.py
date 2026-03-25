from __future__ import annotations

import re
from dataclasses import dataclass

from app.extensions import db
from app.models.models import Device, Port, VLAN


@dataclass(frozen=True)
class DeviceProfile:
    model_hint: str
    ports: int
    poe_ports: int = 0


KNOWN_PROFILES = [
    DeviceProfile(model_hint="gs1900-24", ports=24, poe_ports=12),
    DeviceProfile(model_hint="gs1900-24e", ports=24, poe_ports=0),
    DeviceProfile(model_hint="gs1900-8", ports=8, poe_ports=4),
    DeviceProfile(model_hint="gs1920-24", ports=24, poe_ports=12),
    DeviceProfile(model_hint="er-x", ports=5, poe_ports=1),
    DeviceProfile(model_hint="edgerouterx", ports=5, poe_ports=1),
    DeviceProfile(model_hint="edgerouter-x", ports=5, poe_ports=1),
]


_PORT_ROW_RE = re.compile(
    r"^(?:\s*(?:port|ethernet)?\s*)?(?P<port>\d{1,3}|eth\d{1,2})\s+"
    r"(?P<state>up|down|disabled|enable|disable|connected|notconnect|not-connected|linkup|linkdown)\b",
    flags=re.IGNORECASE,
)


MODEL_PORT_HINTS = {
    "-8": 8,
    "-16": 16,
    "-24": 24,
    "-48": 48,
}


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower().replace(" ", "")


def infer_port_count(device: Device) -> int:
    model_text = _normalize(device.model)
    name_text = _normalize(device.name)

    for profile in KNOWN_PROFILES:
        if profile.model_hint in model_text or profile.model_hint in name_text:
            return profile.ports

    for suffix, ports in MODEL_PORT_HINTS.items():
        if suffix in model_text or suffix in name_text:
            return ports

    return 24


def ensure_device_inventory(device: Device, port_count: int | None = None) -> tuple[int, int]:
    expected_ports = max(1, min(port_count or infer_port_count(device), 128))

    existing_ports = {
        port.port_number: port
        for port in Port.query.filter_by(device_id=device.id).all()
    }

    created = 0
    for number in range(1, expected_ports + 1):
        if number in existing_ports:
            continue
        db.session.add(Port(device_id=device.id, port_number=number, admin_enabled=True, link_state="down", vlan_id=1))
        created += 1

    if not VLAN.query.filter_by(device_id=device.id, vlan_id=1).first():
        db.session.add(VLAN(device_id=device.id, vlan_id=1, name="Default"))

    if created:
        db.session.commit()

    total = Port.query.filter_by(device_id=device.id).count()
    return created, total


def parse_interface_rows(raw_output: str | list[dict]) -> list[dict]:
    if isinstance(raw_output, list):
        lines = []
        for item in raw_output:
            line = str(item.get("raw", ""))
            lines.extend(line.splitlines())
    else:
        lines = str(raw_output or "").splitlines()

    parsed: list[dict] = []
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        match = _PORT_ROW_RE.match(cleaned)
        if not match:
            continue

        token = match.group("port").lower()
        if token.startswith("eth"):
            port_number = int(token.removeprefix("eth")) + 1
        else:
            port_number = int(token)

        state_token = match.group("state").lower().replace("-", "")
        if state_token in {"up", "connected", "enable", "linkup"}:
            link_state = "up"
            admin_enabled = True
        elif state_token in {"down", "notconnect", "linkdown"}:
            link_state = "down"
            admin_enabled = True
        else:
            link_state = "down"
            admin_enabled = False

        parsed.append({"port_number": port_number, "link_state": link_state, "admin_enabled": admin_enabled})

    return parsed


def apply_interface_snapshot(device: Device, interfaces: list[dict] | str) -> int:
    parsed = parse_interface_rows(interfaces)
    if not parsed:
        return 0

    existing_ports = {
        port.port_number: port
        for port in Port.query.filter_by(device_id=device.id).all()
    }

    for entry in parsed:
        port = existing_ports.get(entry["port_number"])
        if not port:
            port = Port(device_id=device.id, port_number=entry["port_number"], vlan_id=1)
            db.session.add(port)
        port.link_state = entry["link_state"]
        port.admin_enabled = entry["admin_enabled"]

    db.session.commit()
    return len(parsed)
