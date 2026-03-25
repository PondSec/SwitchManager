from flask import Blueprint, flash, jsonify, render_template, request
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.network_forms import BulkPortForm, PortConfigForm
from app.models.models import Port, VLAN
from app.services.audit_service import write_audit
from app.services.validation import validate_port_list
from app.utils.device_context import get_selected_device
from app.utils.driver_factory import get_driver

bp = Blueprint("ports", __name__, url_prefix="/ports")


def _serialize_port(port: Port) -> dict:
    status = "disabled" if not port.admin_enabled else "active"
    tagged_policy = "allow_all" if port.vlan_mode == "tagged" else "custom"
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
        "profile": "auto",
        "speed": port.speed or "auto",
        "duplex": port.duplex or "auto",
        "connectedDevice": port.alias or "",
        "txRate": "0 Mbps",
        "rxRate": "0 Mbps",
        "linkState": port.link_state or "down",
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

    if device and form.submit.data and form.validate_on_submit():
        driver = get_driver(device)
        try:
            result_admin = driver.set_port_admin_state(form.port_number.data, form.admin_enabled.data, dry_run=form.dry_run.data)
            result_vlan = driver.assign_port_to_vlan(
                form.port_number.data,
                form.vlan_id.data,
                form.vlan_mode.data,
                dry_run=form.dry_run.data,
            )
            preview = {"commands": result_admin["commands"] + result_vlan["commands"], "dry_run": form.dry_run.data}
            port = Port.query.filter_by(device_id=device.id, port_number=form.port_number.data).first()
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
        ports_payload=[_serialize_port(port) for port in ports],
        vlan_options=[{"id": vlan.vlan_id, "name": vlan.name} for vlan in vlans],
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

    for port in ports:
        status = updates.get("status")
        if status == "active":
            port.admin_enabled = True
        elif status in {"disabled", "restricted"}:
            port.admin_enabled = False

        vlan_native = updates.get("vlanNative")
        if isinstance(vlan_native, int):
            port.vlan_id = vlan_native

        tagged_policy = updates.get("taggedPolicy")
        if tagged_policy == "allow_all":
            port.vlan_mode = "tagged"
        elif tagged_policy == "block_all":
            port.vlan_mode = "excluded"
        elif tagged_policy == "custom":
            port.vlan_mode = "untagged"

        poe_mode = updates.get("poeMode")
        if poe_mode == "poe_plus":
            port.poe_enabled = True
        elif poe_mode == "off":
            port.poe_enabled = False

        profile = updates.get("profile")
        if profile in {"auto", "manual"}:
            port.speed = "auto" if profile == "auto" else (updates.get("speed") or "1G")
            port.duplex = "auto" if profile == "auto" else (updates.get("duplex") or "full")

    db.session.commit()
    write_audit(current_user.username, "port_bulk_update", device.name, str(payload), "success")
    return jsonify({"ports": [_serialize_port(port) for port in ports]})


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
    return render_template("partials/port_detail.html", port=port)
