from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.device_forms import DeviceForm
from app.models.models import AuditLog, Device, NetworkProfile, Port, VLAN
from app.services.audit_service import write_audit
from app.services.device_inventory import apply_interface_snapshot, ensure_device_inventory
from app.utils.device_context import set_selected_device
from app.utils.driver_factory import get_driver

bp = Blueprint("devices", __name__, url_prefix="/devices")


def _extract_value(raw: str, keys: list[str]) -> str | None:
    for line in raw.splitlines():
        normalized = line.strip()
        lower = normalized.lower()
        for key in keys:
            if key in lower and ":" in normalized:
                return normalized.split(":", 1)[1].strip()
    return None


@bp.route("/")
@login_required
def index():
    devices = Device.query.order_by(Device.name.asc()).all()
    filters = {
        "q": (request.args.get("q") or "").strip().lower(),
        "status": (request.args.get("status") or "all").lower(),
        "sort": (request.args.get("sort") or "name").lower(),
        "view": (request.args.get("view") or "table").lower(),
    }

    filtered = []
    for device in devices:
        if filters["q"] and filters["q"] not in f"{device.name} {device.host} {device.model}".lower():
            continue
        if filters["status"] != "all" and device.status != filters["status"]:
            continue
        filtered.append(device)

    if filters["sort"] == "status":
        filtered.sort(key=lambda d: (d.status, d.name.lower()))
    elif filters["sort"] == "model":
        filtered.sort(key=lambda d: (d.model.lower(), d.name.lower()))
    elif filters["sort"] == "ip":
        filtered.sort(key=lambda d: d.host)
    else:
        filtered.sort(key=lambda d: d.name.lower())

    favorites = filtered[:5]
    return render_template("devices/index.html", devices=filtered, filters=filters, favorites=favorites)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = DeviceForm()
    if form.validate_on_submit():
        device = Device(
            name=form.name.data,
            host=form.host.data,
            ssh_port=form.ssh_port.data,
            username=form.username.data,
            password=form.password.data,
            key_path=(form.key_path.data or None),
            driver_type=form.driver_type.data,
            model=form.model.data or "Unbekannt",
        )
        db.session.add(device)
        db.session.commit()
        ensure_device_inventory(device, form.inventory_port_count.data)
        write_audit(current_user.username, "device_create", device.name, f"Device {device.host} erstellt", "success")
        flash("Gerät gespeichert.", "success")
        return redirect(url_for("devices.detail", device_id=device.id))
    return render_template("devices/form.html", form=form, title="Switch hinzufügen")


@bp.route("/<int:device_id>")
@login_required
def detail(device_id: int):
    device = Device.query.get_or_404(device_id)
    set_selected_device(device.id)

    ensure_device_inventory(device)
    ports = Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all()
    vlans = VLAN.query.filter_by(device_id=device.id).order_by(VLAN.vlan_id.asc()).all()
    profiles = NetworkProfile.query.order_by(NetworkProfile.name.asc()).all()
    events = AuditLog.query.filter(AuditLog.target == device.name).order_by(AuditLog.created_at.desc()).limit(100).all()

    stats = {
        "port_total": len(ports),
        "port_up": len([p for p in ports if p.link_state == "up" and p.admin_enabled]),
        "port_down": len([p for p in ports if p.link_state == "down" and p.admin_enabled]),
        "port_disabled": len([p for p in ports if not p.admin_enabled]),
        "poe_on": len([p for p in ports if p.poe_enabled]),
    }
    return render_template(
        "devices/detail.html",
        device=device,
        ports=ports,
        vlans=vlans,
        profiles=profiles,
        events=events,
        stats=stats,
    )


@bp.route("/<int:device_id>/port/<int:port_id>/update", methods=["POST"])
@login_required
def update_port(device_id: int, port_id: int):
    device = Device.query.get_or_404(device_id)
    port = Port.query.filter_by(device_id=device.id, id=port_id).first_or_404()

    new_alias = request.form.get("alias", port.alias)
    new_vlan_id = int(request.form.get("vlan_id", port.vlan_id))
    new_vlan_mode = request.form.get("vlan_mode", port.vlan_mode)
    new_admin_enabled = request.form.get("admin_enabled") == "on"
    new_poe_enabled = request.form.get("poe_enabled") == "on"

    driver = get_driver(device)
    try:
        driver.connect()
        driver.set_port_admin_state(port.port_number, new_admin_enabled, dry_run=False)
        driver.assign_port_to_vlan(port.port_number, new_vlan_id, new_vlan_mode, dry_run=False)
        driver.set_poe_state(port.port_number, new_poe_enabled, dry_run=False)

        port.alias = new_alias
        port.vlan_id = new_vlan_id
        port.vlan_mode = new_vlan_mode
        port.admin_enabled = new_admin_enabled
        port.poe_enabled = new_poe_enabled
        db.session.commit()

        write_audit(
            current_user.username,
            "port_update",
            device.name,
            f"Port {port.port_number}: VLAN {port.vlan_id}/{port.vlan_mode}, admin={port.admin_enabled}, poe={port.poe_enabled}",
            "success",
        )
        flash(f"Port {port.port_number} aktualisiert und auf Gerät übernommen.", "success")
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        write_audit(current_user.username, "port_update", device.name, "Port-Update fehlgeschlagen", "failed", str(exc))
        flash(f"Port-Update fehlgeschlagen: {exc}", "error")
    finally:
        driver.close()
    return redirect(url_for("devices.detail", device_id=device.id, tab="ports", selected_port=port.id))


@bp.route("/<int:device_id>/action/<string:action>", methods=["POST"])
@login_required
def action(device_id: int, action: str):
    device = Device.query.get_or_404(device_id)

    if action == "sync":
        driver = get_driver(device)
        try:
            driver.connect()
            synced_interfaces = 0
            try:
                info = driver.get_system_info()
                raw_info = str(info.get("raw", ""))
                model = _extract_value(raw_info, ["model"]) or _extract_value(raw_info, ["product model"])
                firmware = _extract_value(raw_info, ["firmware", "version"])
                mgmt_ip = _extract_value(raw_info, ["management ip", "ip address"])
                if model:
                    device.model = model
                if firmware:
                    device.firmware = firmware
                if mgmt_ip:
                    device.mgmt_ip = mgmt_ip
            except Exception:  # noqa: BLE001
                pass

            try:
                interfaces = driver.get_interfaces()
                synced_interfaces = apply_interface_snapshot(device, interfaces)
            except Exception:  # noqa: BLE001
                synced_interfaces = 0

            created_ports, total_ports = ensure_device_inventory(device)
            device.status = "online"
            db.session.commit()

            details = f"Sync ok: interfaces={synced_interfaces}, created_ports={created_ports}, total_ports={total_ports}"
            write_audit(current_user.username, "device_sync", device.name, details, "success")
            flash(f"Synchronisierung erfolgreich ({total_ports} Ports verfügbar).", "success")
        except Exception as exc:  # noqa: BLE001
            device.status = "offline"
            db.session.commit()
            write_audit(current_user.username, "device_sync", device.name, "Synchronisierung fehlgeschlagen", "failed", str(exc))
            flash(f"Synchronisierung fehlgeschlagen: {exc}", "error")
        finally:
            driver.close()
    elif action == "reconnect":
        return redirect(url_for("devices.test_connection", device_id=device.id))
    elif action == "remove":
        name = device.name
        db.session.delete(device)
        db.session.commit()
        write_audit(current_user.username, "device_delete", name, "Gerät entfernt", "success")
        flash("Gerät entfernt.", "success")
        return redirect(url_for("devices.index"))

    return redirect(url_for("devices.detail", device_id=device.id))


@bp.route("/<int:device_id>/edit", methods=["GET", "POST"])
@login_required
def edit(device_id: int):
    device = Device.query.get_or_404(device_id)
    form = DeviceForm(obj=device)
    if form.validate_on_submit():
        form.populate_obj(device)
        device.key_path = (device.key_path or "").strip() or None
        ensure_device_inventory(device, form.inventory_port_count.data)
        db.session.commit()
        write_audit(current_user.username, "device_edit", device.name, "Gerät bearbeitet", "success")
        flash("Gerät aktualisiert.", "success")
        return redirect(url_for("devices.detail", device_id=device.id))
    return render_template("devices/form.html", form=form, title=f"Gerät bearbeiten: {device.name}")


@bp.route("/<int:device_id>/delete", methods=["POST"])
@login_required
def delete(device_id: int):
    device = Device.query.get_or_404(device_id)
    name = device.name
    db.session.delete(device)
    db.session.commit()
    write_audit(current_user.username, "device_delete", name, "Gerät entfernt", "success")
    flash("Gerät gelöscht.", "success")
    return redirect(url_for("devices.index"))


@bp.route("/<int:device_id>/test", methods=["POST"])
@login_required
def test_connection(device_id: int):
    device = Device.query.get_or_404(device_id)
    driver = get_driver(device)
    try:
        driver.connect()
        device.status = "online"
        db.session.commit()
        flash("Verbindung erfolgreich.", "success")
        write_audit(current_user.username, "device_test", device.name, "SSH Verbindung erfolgreich", "success")
    except Exception as exc:  # noqa: BLE001
        device.status = "offline"
        db.session.commit()
        flash(f"Verbindung fehlgeschlagen: {exc}", "error")
        write_audit(current_user.username, "device_test", device.name, "SSH Verbindung fehlgeschlagen", "failed", str(exc))
    finally:
        driver.close()
    return redirect(request.referrer or url_for("devices.index"))


@bp.route("/<int:device_id>/select", methods=["GET", "POST"])
@login_required
def select(device_id: int):
    device = Device.query.get_or_404(device_id)
    set_selected_device(device.id)
    flash(f"Aktives Gerät: {device.name}", "success")
    return redirect(request.referrer or url_for("dashboard.index"))
