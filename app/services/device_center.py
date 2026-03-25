from __future__ import annotations

from collections import defaultdict

from app.models.models import Port
from app.services.device_inventory import apply_interface_snapshot, apply_vlan_snapshot
from app.utils.driver_factory import get_driver


def _human_bytes(value: int | float) -> str:
    size = float(value or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def _device_family(driver_type: str) -> str:
    if driver_type == "edgeos-ssh":
        return "Router"
    if driver_type == "zyxel-ssh":
        return "Switch"
    return "Netzwerkgerät"


def _network_label(vlan_id: int | None, vlan_names: dict[int, str]) -> str:
    if vlan_id is None:
        return "Unbekannt"
    name = vlan_names.get(vlan_id)
    return f"{name} ({vlan_id})" if name else f"VLAN {vlan_id}"


def load_device_center_snapshot(device) -> dict:
    driver = get_driver(device)
    warnings: list[str] = []

    live_info: dict = {}
    interfaces: list[dict] = []
    vlans: list[dict] = []
    mac_table: list[dict] = []
    arp_table: list[dict] = []
    lldp_neighbors: list[dict] = []
    interface_metrics: list[dict] = []
    routes: list[dict] = []
    dhcp_leases: list[dict] = []
    offload_status: dict = {}

    try:
        driver.connect()

        try:
            live_info = driver.get_system_info()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Systeminformationen konnten nicht geladen werden: {exc}")

        try:
            interfaces = driver.get_interfaces()
            apply_interface_snapshot(device, interfaces)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Portstatus konnte nicht geladen werden: {exc}")
            interfaces = []

        try:
            vlans = driver.get_vlans()
            apply_vlan_snapshot(device, vlans)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"VLAN-Ansicht konnte nicht geladen werden: {exc}")
            vlans = []

        if hasattr(driver, "get_mac_table"):
            try:
                mac_table = driver.get_mac_table()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"MAC-Tabelle konnte nicht geladen werden: {exc}")

        if hasattr(driver, "get_arp_table"):
            try:
                arp_table = driver.get_arp_table()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"ARP-Tabelle konnte nicht geladen werden: {exc}")

        if hasattr(driver, "get_lldp_neighbors"):
            try:
                lldp_neighbors = driver.get_lldp_neighbors()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"LLDP-Nachbarn konnten nicht geladen werden: {exc}")

        if hasattr(driver, "get_routes"):
            try:
                routes = driver.get_routes()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Routing-Tabelle konnte nicht geladen werden: {exc}")

        if hasattr(driver, "get_dhcp_leases"):
            try:
                dhcp_leases = driver.get_dhcp_leases()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"DHCP-Leases konnten nicht geladen werden: {exc}")

        if hasattr(driver, "get_offload_status"):
            try:
                offload_status = driver.get_offload_status()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Offload/DPI-Status konnte nicht geladen werden: {exc}")

        if hasattr(driver, "get_interface_metrics"):
            try:
                if device.driver_type == "zyxel-ssh":
                    active_ports = {int(item["port_number"]) for item in interfaces if item.get("link_state") == "up" and item.get("port_number")}
                    active_ports.update(int(item["port_number"]) for item in mac_table if item.get("port_number"))
                    active_ports.update(int(item["port_number"]) for item in lldp_neighbors if item.get("port_number"))
                    selected_ports = sorted(active_ports)[:12]
                    interface_metrics = driver.get_interface_metrics(selected_ports)
                else:
                    interface_metrics = driver.get_interface_metrics()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Traffic-Metriken konnten nicht geladen werden: {exc}")
    finally:
        driver.close()

    db_ports = {
        port.port_number: port
        for port in Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all()
    }
    vlan_names = {int(item["vlan_id"]): str(item.get("name") or f"VLAN {item['vlan_id']}") for item in vlans if item.get("vlan_id")}
    metric_by_port = {int(item["port_number"]): item for item in interface_metrics if item.get("port_number") is not None}
    metric_by_name = {str(item["name"]): item for item in interface_metrics if item.get("name")}
    lldp_by_port = {int(item["port_number"]): item for item in lldp_neighbors if item.get("port_number")}

    client_map: dict[str, dict] = {}

    def ensure_client(key: str) -> dict:
        client = client_map.get(key)
        if client:
            return client
        client = {
            "name": "",
            "ip": "",
            "mac": "",
            "network": "",
            "attachment": "",
            "source": set(),
            "lease_expires": "",
            "entry_type": "",
        }
        client_map[key] = client
        return client

    for lease in dhcp_leases:
        key = lease.get("mac") or lease.get("ip")
        if not key:
            continue
        client = ensure_client(str(key).lower())
        client["name"] = lease.get("client_name") or client["name"]
        client["ip"] = lease.get("ip") or client["ip"]
        client["mac"] = lease.get("mac") or client["mac"]
        client["network"] = lease.get("pool") or client["network"]
        client["lease_expires"] = lease.get("lease_expires") or client["lease_expires"]
        client["source"].add("DHCP")

    for arp in arp_table:
        key = arp.get("mac") if arp.get("mac") and arp.get("mac") != "(incomplete)" else arp.get("ip")
        if not key:
            continue
        client = ensure_client(str(key).lower())
        client["ip"] = arp.get("ip") or client["ip"]
        if arp.get("mac") and arp.get("mac") != "(incomplete)":
            client["mac"] = arp.get("mac")
        client["attachment"] = arp.get("interface") or client["attachment"]
        client["source"].add("ARP")

    for entry in mac_table:
        key = entry.get("mac")
        if not key:
            continue
        client = ensure_client(str(key).lower())
        client["mac"] = entry.get("mac") or client["mac"]
        client["network"] = _network_label(entry.get("vlan_id"), vlan_names)
        client["attachment"] = entry.get("port") or client["attachment"]
        client["entry_type"] = entry.get("entry_type") or client["entry_type"]
        client["source"].add("MAC")

    clients = []
    for item in client_map.values():
        clients.append({
            **item,
            "name": item["name"] or item["ip"] or item["mac"] or "Unbekannter Client",
            "source": ", ".join(sorted(item["source"])) or "Unbekannt",
            "network": item["network"] or "Unbekannt",
            "attachment": item["attachment"] or "Unbekannt",
        })
    clients.sort(key=lambda item: (item["attachment"], item["name"].lower()))

    macs_by_port: dict[int, int] = defaultdict(int)
    for entry in mac_table:
        if entry.get("port_number"):
            macs_by_port[int(entry["port_number"])] += 1

    port_cards = []
    for item in interfaces:
        port_number = item.get("port_number")
        if port_number is None:
            continue
        stored = db_ports.get(int(port_number))
        metrics = metric_by_port.get(int(port_number), {})
        neighbor = lldp_by_port.get(int(port_number), {})
        total_bytes = int(metrics.get("rx_bytes", 0)) + int(metrics.get("tx_bytes", 0))
        speed = item.get("speed") or (stored.speed if stored else None)
        duplex = item.get("duplex") or (stored.duplex if stored else None)
        vlan_value = item.get("vlan_id", stored.vlan_id if stored else None)
        client_count = macs_by_port.get(int(port_number), 0)
        health_state = "disabled"
        if item.get("admin_enabled", True):
            if item.get("link_state") == "up":
                health_state = "uplink" if neighbor else "active"
            elif client_count:
                health_state = "attention"
            else:
                health_state = "idle"
        port_cards.append({
            "port_number": int(port_number),
            "label": stored.alias if stored and stored.alias else item.get("alias") or f"Port {port_number}",
            "link_state": item.get("link_state", "down"),
            "admin_enabled": bool(item.get("admin_enabled", True)),
            "speed": speed,
            "duplex": duplex,
            "poe_enabled": bool(item.get("poe_enabled", stored.poe_enabled if stored else False)),
            "vlan_label": _network_label(vlan_value, vlan_names),
            "client_count": client_count,
            "neighbor_name": neighbor.get("sys_name") or neighbor.get("device_id") or "",
            "traffic_total": total_bytes,
            "traffic_human": _human_bytes(total_bytes),
            "health_state": health_state,
        })

    port_cards.sort(key=lambda item: item["port_number"])

    traffic_rows = []
    for metric in interface_metrics:
        total_bytes = int(metric.get("rx_bytes", 0)) + int(metric.get("tx_bytes", 0))
        traffic_rows.append({
            "port_number": metric.get("port_number"),
            "name": metric.get("name") or f"Port {metric.get('port_number')}",
            "description": metric.get("description") or metric.get("address") or "",
            "link_state": metric.get("link_state", "down"),
            "rx_bytes": int(metric.get("rx_bytes", 0)),
            "tx_bytes": int(metric.get("tx_bytes", 0)),
            "rx_human": _human_bytes(int(metric.get("rx_bytes", 0))),
            "tx_human": _human_bytes(int(metric.get("tx_bytes", 0))),
            "total_bytes": total_bytes,
            "total_human": _human_bytes(total_bytes),
            "errors": int(metric.get("input_errors", 0) or metric.get("rx_errors", 0)) + int(metric.get("output_errors", 0) or metric.get("tx_errors", 0)),
            "drops": int(metric.get("rx_dropped", 0)) + int(metric.get("tx_dropped", 0)),
        })
    traffic_rows.sort(key=lambda item: item["total_bytes"], reverse=True)

    vlan_cards = []
    clients_per_network: dict[str, int] = defaultdict(int)
    for client in clients:
        clients_per_network[client["network"]] += 1
    for item in vlans:
        vlan_id = int(item["vlan_id"])
        label = _network_label(vlan_id, vlan_names)
        vlan_cards.append({
            "vlan_id": vlan_id,
            "name": item.get("name") or f"VLAN {vlan_id}",
            "address": item.get("address") or "",
            "tagged_ports": item.get("tagged_ports") or "",
            "untagged_ports": item.get("untagged_ports") or "",
            "client_count": clients_per_network.get(label, 0),
            "label": label,
        })
    vlan_cards.sort(key=lambda item: item["vlan_id"])

    alerts = []
    for port in port_cards:
        if port["link_state"] == "down" and port["admin_enabled"] and port["client_count"] == 0:
            continue
        if port["link_state"] == "down" and port["admin_enabled"]:
            alerts.append(f"Port {port['port_number']} ist administrativ aktiv, aber aktuell down.")
        if port["neighbor_name"] and port["client_count"] > 0:
            alerts.append(f"Port {port['port_number']} hat LLDP-Nachbarn und {port['client_count']} gelernte MACs.")

    for row in traffic_rows[:8]:
        if row["errors"] or row["drops"]:
            alerts.append(f"{row['name']} meldet Fehler/Drops ({row['errors']} / {row['drops']}).")

    if offload_status:
        if offload_status.get("traffic_export") == "disabled":
            alerts.append("Traffic-Analyse-Export auf dem EdgeRouter ist derzeit deaktiviert.")
        if offload_status.get("dpi") == "disabled":
            alerts.append("DPI ist derzeit deaktiviert.")

    discovery_cards = [
        {"label": "MAC", "count": len(mac_table)},
        {"label": "ARP", "count": len(arp_table)},
        {"label": "DHCP", "count": len(dhcp_leases)},
        {"label": "LLDP", "count": len(lldp_neighbors)},
        {"label": "Routes", "count": len(routes)},
    ]

    summary = {
        "family": _device_family(device.driver_type),
        "ports_total": len(port_cards),
        "ports_up": len([item for item in port_cards if item["link_state"] == "up"]),
        "ports_disabled": len([item for item in port_cards if not item["admin_enabled"]]),
        "ports_attention": len([item for item in port_cards if item["health_state"] == "attention"]),
        "ports_poe": len([item for item in port_cards if item["poe_enabled"]]),
        "uplinks_total": len([item for item in port_cards if item["neighbor_name"]]),
        "clients_total": len(clients),
        "vlans_total": len(vlan_cards),
        "neighbors_total": len(lldp_neighbors),
        "arp_total": len(arp_table),
        "mac_total": len(mac_table),
        "dhcp_total": len(dhcp_leases),
        "routes_total": len(routes),
        "traffic_total": _human_bytes(sum(item["total_bytes"] for item in traffic_rows)),
        "alerts_total": len(alerts),
    }

    return {
        "device": device,
        "live_info": live_info,
        "warnings": warnings,
        "summary": summary,
        "port_cards": port_cards,
        "clients": clients,
        "vlan_cards": vlan_cards,
        "traffic_rows": traffic_rows,
        "mac_table": mac_table,
        "arp_table": arp_table,
        "lldp_neighbors": lldp_neighbors,
        "routes": routes,
        "dhcp_leases": dhcp_leases,
        "offload_status": offload_status,
        "discovery_cards": discovery_cards,
        "alerts": alerts[:10],
    }
