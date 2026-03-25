from flask import Blueprint, flash, jsonify, render_template, request
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.network_forms import BulkPortForm, PortConfigForm
from app.models.models import Device, Port, VLAN
from app.services.audit_service import write_audit
from app.services.device_center import load_device_center_snapshot
from app.services.validation import validate_port_list
from app.services.zyxel_web_config import ZyxelWebConfigClient
from app.utils.device_context import get_selected_device
from app.utils.driver_factory import get_driver

bp = Blueprint("ports", __name__, url_prefix="/ports")


def _parse_zyxel_port_members(text: str | None) -> set[int]:
    members: set[int] = set()
    for token in (text or "").replace(";", ",").split(","):
        raw = token.strip()
        if not raw or raw.lower().startswith("lag"):
            continue
        if "-" in raw:
            start_raw, end_raw = raw.split("-", 1)
            if start_raw.strip().isdigit() and end_raw.strip().isdigit():
                start = int(start_raw.strip())
                end = int(end_raw.strip())
                for value in range(min(start, end), max(start, end) + 1):
                    members.add(value)
            continue
        if raw.isdigit():
            members.add(int(raw))
    return members


def _derive_zyxel_memberships(port_number: int, vlans: list[dict]) -> dict[int, str]:
    memberships: dict[int, str] = {}
    for vlan in vlans:
        vlan_id = vlan.get("vlan_id")
        if vlan_id is None:
            continue
        if port_number in _parse_zyxel_port_members(vlan.get("untagged_ports")):
            memberships[int(vlan_id)] = "3"
        elif port_number in _parse_zyxel_port_members(vlan.get("tagged_ports")):
            memberships[int(vlan_id)] = "2"
        else:
            memberships[int(vlan_id)] = "0"
    return memberships


def _bulk_apply_zyxel_updates(device: Device, ports: list[Port], updates: dict) -> list[Port]:
    driver = get_driver(device)
    try:
        driver.connect()
        live_vlans = driver.get_vlans()
    finally:
        driver.close()

    client = ZyxelWebConfigClient(device.host, device.username, device.password or "")
    pending_save = False

    for port in ports:
        current_memberships = _derive_zyxel_memberships(port.port_number, live_vlans)
        desired_memberships = dict(current_memberships)

        desired_admin = port.admin_enabled
        status = updates.get("status")
        if status == "active":
            desired_admin = True
        elif status in {"disabled", "restricted"}:
            desired_admin = False

        desired_vlan_id = int(port.vlan_id or 1)
        vlan_native = updates.get("vlanNative")
        if isinstance(vlan_native, int) and 1 <= vlan_native <= 4094:
            desired_vlan_id = vlan_native

        desired_vlan_mode = port.vlan_mode
        tagged_policy = updates.get("taggedPolicy")
        if tagged_policy == "allow_all":
            desired_vlan_mode = "tagged"
        elif tagged_policy == "block_all":
            desired_vlan_mode = "excluded"
        elif tagged_policy == "custom":
            desired_vlan_mode = "untagged"

        if desired_vlan_id not in desired_memberships:
            desired_memberships[desired_vlan_id] = "0"

        if desired_vlan_mode == "untagged":
            for vlan_id, code in list(desired_memberships.items()):
                if code == "3" and vlan_id != desired_vlan_id:
                    desired_memberships[vlan_id] = "0"
            desired_memberships[desired_vlan_id] = "3"
        elif desired_vlan_mode == "tagged":
            for vlan_id, code in list(desired_memberships.items()):
                if code == "3":
                    desired_memberships[vlan_id] = "0"
            desired_memberships[desired_vlan_id] = "2"
        elif desired_vlan_mode == "excluded":
            for vlan_id, code in list(desired_memberships.items()):
                if vlan_id == desired_vlan_id or code == "3":
                    desired_memberships[vlan_id] = "0"

        changed_memberships = {
            vlan_id: code
            for vlan_id, code in desired_memberships.items()
            if current_memberships.get(vlan_id, "0") != code
        }

        port_changed = False
        if desired_admin != port.admin_enabled:
            client.set_port_physical(port.port_number, admin_enabled=desired_admin, save=False)
            port_changed = True

        if desired_vlan_id != int(port.vlan_id or 1):
            client.set_port_vlan_settings(port.port_number, pvid=desired_vlan_id, save=False)
            port_changed = True

        if changed_memberships:
            client.set_port_memberships(port.port_number, changed_memberships, save=False)
            port_changed = True

        if not port_changed:
            continue

        port.admin_enabled = desired_admin
        port.vlan_id = desired_vlan_id
        port.vlan_mode = desired_vlan_mode
        pending_save = True

    if pending_save:
        client.save_config()
    return ports


def _serialize_port(
    port: Port,
    snapshot_port: dict | None = None,
    traffic: dict | None = None,
    max_traffic: int = 0,
    poe_supported: bool = True,
    poe_reason: str = "",
    poe_role: str = "none",
    poe_note: str = "",
) -> dict:
    snapshot_port = snapshot_port or {}
    traffic = traffic or {}
    status = "disabled" if not port.admin_enabled else "active"
    tagged_policy = "allow_all" if port.vlan_mode == "tagged" else "custom"
    traffic_total = int(traffic.get("total_bytes", snapshot_port.get("traffic_total", 0)) or 0)
    client_count = int(snapshot_port.get("client_count", 0) or 0)
    neighbor_name = snapshot_port.get("neighbor_name", "")
    connected_device = neighbor_name or (f"{client_count} Clients" if client_count else "")
    return {
        "id": port.id,
        "portNumber": port.port_number,
        "enabled": bool(port.admin_enabled),
        "status": status,
        "vlanNative": port.vlan_id,
        "vlanTagged": [port.vlan_id] if port.vlan_mode == "tagged" else [],
        "taggedPolicy": tagged_policy,
        "poeEnabled": bool(port.poe_enabled),
        "poeMode": "poe_plus" if port.poe_enabled else "off",
        "poeSupported": bool(poe_supported),
        "poeReason": poe_reason,
        "poeRole": poe_role,
        "poeNote": poe_note,
        "profile": "auto",
        "speed": port.speed or "auto",
        "duplex": port.duplex or "auto",
        "alias": port.alias or snapshot_port.get("label") or f"Port {port.port_number}",
        "connectedDevice": connected_device,
        "neighborName": neighbor_name,
        "clientCount": client_count,
        "vlanLabel": snapshot_port.get("vlan_label") or f"VLAN {port.vlan_id}",
        "trafficHuman": traffic.get("total_human", snapshot_port.get("traffic_human", "0 B")),
        "txRate": traffic.get("tx_human", "0 B"),
        "rxRate": traffic.get("rx_human", "0 B"),
        "activityPercent": round((traffic_total / max_traffic * 100), 1) if max_traffic else 0,
        "linkState": port.link_state or "down",
        "healthState": snapshot_port.get("health_state", "idle"),
    }


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = PortConfigForm(prefix="single")
    bulk_form = BulkPortForm(prefix="bulk")
    preview = None
    device = get_selected_device()
    ports = Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all() if device else []
    vlans = VLAN.query.filter_by(device_id=device.id).order_by(VLAN.vlan_id.asc()).all() if device else []
    snapshot = None
    snapshot_warning = ""
    snapshot_ports: dict[int, dict] = {}
    snapshot_traffic: dict[int, dict] = {}
    max_traffic = 0
    poe_support_map: dict[int, bool] = {}
    poe_reason_map: dict[int, str] = {}
    poe_role_map: dict[int, str] = {}
    poe_note_map: dict[int, str] = {}

    if device:
        driver = get_driver(device)
        for port in ports:
            poe_support_map[port.port_number] = driver.supports_poe_port(port.port_number)
            poe_reason_map[port.port_number] = driver.poe_support_reason(port.port_number) if not poe_support_map[port.port_number] else ""
            poe_role_map[port.port_number] = driver.poe_role_for_port(port.port_number)
            poe_note_map[port.port_number] = driver.poe_note_for_port(port.port_number)
        try:
            snapshot = load_device_center_snapshot(device)
            snapshot_ports = {
                int(item["port_number"]): item
                for item in snapshot.get("port_cards", [])
                if item.get("port_number") is not None
            }
            snapshot_traffic = {
                int(item["port_number"]): item
                for item in snapshot.get("traffic_rows", [])
                if item.get("port_number") is not None
            }
            max_traffic = max((item.get("total_bytes", 0) for item in snapshot.get("traffic_rows", [])), default=0)
        except Exception as exc:  # noqa: BLE001
            snapshot_warning = str(exc)

    if device and form.submit.data and form.validate_on_submit():
        driver = get_driver(device)
        try:
            port = Port.query.filter_by(device_id=device.id, port_number=form.port_number.data).first()
            if not form.dry_run.data and device.driver_type != "zyxel-ssh":
                driver.connect()
            result_alias = {"commands": [], "output": []}
            result_admin = {"commands": [], "output": []}
            result_vlan = {"commands": [], "output": []}
            alias_value = form.alias.data or ""

            if not port:
                raise RuntimeError("Port nicht gefunden.")

            if form.vlan_id.data != port.vlan_id or form.vlan_mode.data != port.vlan_mode:
                result_vlan = driver.assign_port_to_vlan(
                    form.port_number.data,
                    form.vlan_id.data,
                    form.vlan_mode.data,
                    dry_run=form.dry_run.data,
                )
            if form.admin_enabled.data != port.admin_enabled:
                result_admin = driver.set_port_admin_state(form.port_number.data, form.admin_enabled.data, dry_run=form.dry_run.data)
            if alias_value != (port.alias or ""):
                result_alias = driver.set_port_alias(form.port_number.data, alias_value, dry_run=form.dry_run.data)
            preview = {"commands": result_vlan["commands"] + result_admin["commands"] + result_alias["commands"], "dry_run": form.dry_run.data}
            if port and not form.dry_run.data:
                port.admin_enabled = form.admin_enabled.data
                port.vlan_id = form.vlan_id.data
                port.vlan_mode = form.vlan_mode.data
                port.alias = form.alias.data or ""
                db.session.commit()
                flash("Port angewendet.", "success")
            else:
                flash("Port-Vorschau erstellt.", "info")
            write_audit(current_user.username, "port_update", device.name, str(preview["commands"]), "success")
        except Exception as exc:  # noqa: BLE001
            flash(str(exc), "error")
            write_audit(current_user.username, "port_update", device.name, "Port Konfiguration fehlgeschlagen", "failed", str(exc))
        finally:
            driver.close()

    if device and bulk_form.submit.data and bulk_form.validate_on_submit():
        driver = get_driver(device)
        try:
            port_numbers = validate_port_list(bulk_form.ports.data)
            commands = []
            for pnum in port_numbers:
                result = driver.set_port_admin_state(pnum, bulk_form.admin_enabled.data, dry_run=True)
                commands.extend(result["commands"])
            preview = {"commands": commands, "dry_run": True}
            flash("Bulk-Vorschau erstellt.", "info")
            write_audit(current_user.username, "port_bulk_preview", device.name, str(commands), "success")
        except Exception as exc:  # noqa: BLE001
            flash(str(exc), "error")
        finally:
            driver.close()

    return render_template(
        "ports/index.html",
        form=form,
        bulk_form=bulk_form,
        ports=ports,
        preview=preview,
        ports_payload=[
            _serialize_port(
                port,
                snapshot_ports.get(port.port_number),
                snapshot_traffic.get(port.port_number),
                max_traffic,
                poe_supported=poe_support_map.get(port.port_number, True),
                poe_reason=poe_reason_map.get(port.port_number, ""),
                poe_role=poe_role_map.get(port.port_number, "none"),
                poe_note=poe_note_map.get(port.port_number, ""),
            )
            for port in ports
        ],
        vlan_options=[{"id": vlan.vlan_id, "name": vlan.name} for vlan in vlans],
        snapshot=snapshot,
        snapshot_warning=snapshot_warning,
    )


@bp.route("/bulk-update", methods=["POST"])
@login_required
def bulk_update():
    device = get_selected_device()
    if not device:
        return jsonify({"error": "Kein Gerät ausgewählt."}), 400

    payload = request.get_json(silent=True) or {}
    port_ids = payload.get("portIds", [])
    updates = payload.get("updates", {})

    if not port_ids:
        return jsonify({"error": "Keine Ports ausgewählt."}), 400

    ports = Port.query.filter(Port.device_id == device.id, Port.id.in_(port_ids)).all()
    if not ports:
        return jsonify({"error": "Ports nicht gefunden."}), 404

    driver = get_driver(device)
    try:
        if device.driver_type == "zyxel-ssh":
            updated_ports = _bulk_apply_zyxel_updates(device, ports, updates)
            db.session.commit()
            write_audit(current_user.username, "port_bulk_update", device.name, str(payload), "success")
            return jsonify({"ports": [_serialize_port(port) for port in updated_ports]})

        planned_updates: list[tuple[Port, bool, int, str, bool]] = []
        requires_connect = False

        for port in ports:
            desired_admin = port.admin_enabled
            status = updates.get("status")
            if status == "active":
                desired_admin = True
            elif status in {"disabled", "restricted"}:
                desired_admin = False

            desired_vlan_id = port.vlan_id
            vlan_native = updates.get("vlanNative")
            if isinstance(vlan_native, int):
                desired_vlan_id = vlan_native

            desired_vlan_mode = port.vlan_mode
            tagged_policy = updates.get("taggedPolicy")
            if tagged_policy == "allow_all":
                desired_vlan_mode = "tagged"
            elif tagged_policy == "block_all":
                desired_vlan_mode = "excluded"
            elif tagged_policy == "custom":
                desired_vlan_mode = "untagged"

            desired_poe_enabled = port.poe_enabled
            poe_mode = updates.get("poeMode")
            if poe_mode == "poe_plus":
                desired_poe_enabled = True
            elif poe_mode == "off":
                desired_poe_enabled = False

            if (
                desired_admin != port.admin_enabled
                or desired_vlan_id != port.vlan_id
                or desired_vlan_mode != port.vlan_mode
                or desired_poe_enabled != port.poe_enabled
            ):
                requires_connect = True

            if desired_poe_enabled != port.poe_enabled and desired_poe_enabled and not driver.supports_poe_port(port.port_number):
                reason = driver.poe_support_reason(port.port_number) or f"PoE wird auf Port {port.port_number} nicht unterstuetzt."
                return jsonify({"error": reason}), 400

            planned_updates.append((port, desired_admin, desired_vlan_id, desired_vlan_mode, desired_poe_enabled))

        if requires_connect and device.driver_type != "zyxel-ssh":
            driver.connect()

        for port, desired_admin, desired_vlan_id, desired_vlan_mode, desired_poe_enabled in planned_updates:
            if desired_vlan_id != port.vlan_id or desired_vlan_mode != port.vlan_mode:
                driver.assign_port_to_vlan(port.port_number, desired_vlan_id, desired_vlan_mode, dry_run=False)
            if desired_admin != port.admin_enabled:
                driver.set_port_admin_state(port.port_number, desired_admin, dry_run=False)
            if desired_poe_enabled != port.poe_enabled:
                driver.set_poe_state(port.port_number, desired_poe_enabled, dry_run=False)

            port.admin_enabled = desired_admin
            port.vlan_id = desired_vlan_id
            port.vlan_mode = desired_vlan_mode
            port.poe_enabled = desired_poe_enabled

            profile = updates.get("profile")
            if profile in {"auto", "manual"}:
                port.speed = "auto" if profile == "auto" else (updates.get("speed") or "1G")
                port.duplex = "auto" if profile == "auto" else (updates.get("duplex") or "full")

        db.session.commit()
        write_audit(current_user.username, "port_bulk_update", device.name, str(payload), "success")
        return jsonify({"ports": [_serialize_port(port) for port in ports]})
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        write_audit(current_user.username, "port_bulk_update", device.name, "Bulk-Port-Update fehlgeschlagen", "failed", str(exc))
        return jsonify({"error": str(exc)}), 400
    finally:
        driver.close()


@bp.route("/refresh")
@login_required
def refresh():
    device = get_selected_device()
    ports = Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all() if device else []
    return render_template("partials/port_table.html", ports=ports)


@bp.route("/<int:port_id>")
@login_required
def detail(port_id: int):
    port = Port.query.get_or_404(port_id)
    device = Device.query.get_or_404(port.device_id)
    live_port = {}
    live_vlans: list[dict] = []
    switch_options: list[str] = []
    port_warning = ""
    zyxel_profile: dict = {}

    driver = get_driver(device)
    try:
        driver.connect()
        interfaces = driver.get_interfaces()
        live_port = next((row for row in interfaces if row.get("port_number") == port.port_number), {})
        if device.driver_type == "zyxel-ssh":
            live_vlans = driver.get_vlans()
        if hasattr(driver, "list_switches"):
            switch_options = [name for name in driver.list_switches() if name]
    except Exception as exc:  # noqa: BLE001
        port_warning = str(exc)
    finally:
        driver.close()

    if device.driver_type == "zyxel-ssh":
        try:
            zyxel_profile = ZyxelWebConfigClient(device.host, device.username, device.password or "").get_port_settings(port.port_number)
            zyxel_profile["available_vlans"] = live_vlans
            zyxel_profile["memberships"] = _derive_zyxel_memberships(port.port_number, live_vlans)
        except Exception as exc:  # noqa: BLE001
            port_warning = f"{port_warning} | {exc}" if port_warning else str(exc)

    return render_template(
        "partials/port_detail.html",
        port=port,
        device=device,
        live_port=live_port,
        live_vlans=live_vlans,
        switch_options=switch_options,
        port_warning=port_warning,
        zyxel_profile=zyxel_profile,
    )
