from flask import Blueprint, flash, render_template, request
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.network_forms import BulkPortForm, PortConfigForm
from app.models.models import Device, Port
from app.services.audit_service import write_audit
from app.services.validation import validate_port_list
from app.utils.driver_factory import get_driver

bp = Blueprint("ports", __name__, url_prefix="/ports")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = PortConfigForm(prefix="single")
    bulk_form = BulkPortForm(prefix="bulk")
    preview = None
    device = Device.query.first()
    ports = Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all() if device else []

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

    return render_template("ports/index.html", form=form, bulk_form=bulk_form, ports=ports, preview=preview)


@bp.route("/refresh")
@login_required
def refresh():
    device = Device.query.first()
    ports = Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all() if device else []
    return render_template("partials/port_table.html", ports=ports)


@bp.route("/<int:port_id>")
@login_required
def detail(port_id: int):
    port = Port.query.get_or_404(port_id)
    return render_template("partials/port_detail.html", port=port)
