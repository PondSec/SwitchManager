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


_PORT_PREFIX_RE = re.compile(r"^\s*(?P<port>\d{1,3}|eth\d{1,2}|ge\d{1,2}|gi\d{1,2})\b", flags=re.IGNORECASE)
_STATE_RE = re.compile(r"\b(up|down|disabled|enable|disable|connected|notconnect|not-connected|linkup|linkdown)\b", flags=re.IGNORECASE)
_SPEED_RE = re.compile(r"\b(auto|\d+(?:\.\d+)?\s?(?:g|gbps|m|mbps|k|kbps))\b", flags=re.IGNORECASE)

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

    if VLAN.query.filter_by(device_id=device.id).count() == 0:
        db.session.add(VLAN(device_id=device.id, vlan_id=1, name="Default"))

    if created:
        db.session.commit()

    total = Port.query.filter_by(device_id=device.id).count()
    return created, total


def apply_vlan_snapshot(device: Device, vlans: list[dict] | str) -> int:
    parsed: list[dict] = []
    if isinstance(vlans, list):
        for item in vlans:
            if "vlan_id" in item:
                parsed.append({
                    "vlan_id": int(item["vlan_id"]),
                    "name": str(item.get("name") or f"VLAN{int(item['vlan_id'])}"),
                })

    if not parsed:
        return 0

    existing = {
        vlan.vlan_id: vlan
        for vlan in VLAN.query.filter_by(device_id=device.id).all()
    }
    seen: set[int] = set()

    for entry in parsed:
        seen.add(entry["vlan_id"])
        vlan = existing.get(entry["vlan_id"])
        if not vlan:
            vlan = VLAN(device_id=device.id, vlan_id=entry["vlan_id"], name=entry["name"])
            db.session.add(vlan)
        else:
            vlan.name = entry["name"]

    for vlan_id, vlan in existing.items():
        if vlan_id not in seen:
            db.session.delete(vlan)

    db.session.commit()
    return len(parsed)


def _parse_port_number(token: str) -> int | None:
    normalized = token.lower()
    if normalized.startswith("eth"):
        return int(normalized.removeprefix("eth")) + 1
    if normalized.startswith("ge") or normalized.startswith("gi"):
        return int(re.sub(r"[^0-9]", "", normalized) or "0")
    if normalized.isdigit():
        return int(normalized)
    return None


def _extract_state(line: str) -> tuple[str, bool]:
    lowered = line.lower().replace("-", "")
    state_match = _STATE_RE.search(lowered)
    state_token = state_match.group(1).lower().replace("-", "") if state_match else ""

    if state_token in {"up", "connected", "enable", "linkup"}:
        return "up", True
    if state_token in {"down", "notconnect", "linkdown"}:
        return "down", True
    if "disabled" in lowered or " disable" in lowered:
        return "down", False
    return "down", True


def _extract_speed_duplex(line: str) -> tuple[str | None, str | None]:
    lower = line.lower()
    speed_match = _SPEED_RE.search(lower)
    speed = speed_match.group(1).replace(" ", "") if speed_match else None
    if speed and speed in {"g", "m", "k"}:
        speed = None

    duplex = None
    if "full" in lower:
        duplex = "full"
    elif "half" in lower:
        duplex = "half"
    return speed, duplex


def parse_interface_rows(raw_output: str | list[dict]) -> list[dict]:
    parsed: list[dict] = []
    seen: set[int] = set()

    if isinstance(raw_output, list):
        lines = []
        for item in raw_output:
            if "port_number" in item:
                port_number = int(item["port_number"])
                if port_number not in seen:
                    parsed.append({
                        "port_number": port_number,
                        "link_state": str(item.get("link_state", "down")),
                        "admin_enabled": bool(item.get("admin_enabled", True)),
                        "speed": item.get("speed"),
                        "duplex": item.get("duplex"),
                        "alias": item.get("alias"),
                        "vlan_id": item.get("vlan_id"),
                        "vlan_mode": item.get("vlan_mode"),
                        "poe_enabled": item.get("poe_enabled"),
                    })
                    seen.add(port_number)
            lines.extend(str(item.get("raw", "")).splitlines())
    else:
        lines = str(raw_output or "").splitlines()

    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue

        match = _PORT_PREFIX_RE.match(cleaned)
        if not match:
            continue

        port_number = _parse_port_number(match.group("port"))
        if not port_number or port_number in seen:
            continue

        link_state, admin_enabled = _extract_state(cleaned)
        speed, duplex = _extract_speed_duplex(cleaned)

        parsed.append({
            "port_number": port_number,
            "link_state": link_state,
            "admin_enabled": admin_enabled,
            "speed": speed,
            "duplex": duplex,
        })
        seen.add(port_number)

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
        if entry.get("speed"):
            port.speed = entry["speed"]
        if entry.get("duplex"):
            port.duplex = entry["duplex"]
        if entry.get("alias") is not None:
            port.alias = str(entry["alias"])
        if entry.get("vlan_id") is not None:
            port.vlan_id = int(entry["vlan_id"])
        if entry.get("vlan_mode"):
            port.vlan_mode = str(entry["vlan_mode"])
        if entry.get("poe_enabled") is not None:
            port.poe_enabled = bool(entry["poe_enabled"])

    db.session.commit()
    return len(parsed)
