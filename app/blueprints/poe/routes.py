from flask import Blueprint, flash, render_template
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.network_forms import PoEForm
from app.models.models import Device, Port
from app.services.audit_service import write_audit
from app.utils.device_context import get_selected_device
from app.utils.driver_factory import get_driver

bp = Blueprint("poe", __name__, url_prefix="/poe")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = PoEForm()
    preview = None
    device = get_selected_device()
    ports = Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all() if device else []
    poe_support_map: dict[int, bool] = {}
    poe_reason_map: dict[int, str] = {}
    poe_role_map: dict[int, str] = {}
    poe_note_map: dict[int, str] = {}
    poe_supported_count = 0
    if device:
        driver = get_driver(device)
        for port in ports:
            poe_support_map[port.port_number] = driver.supports_poe_port(port.port_number)
            poe_reason_map[port.port_number] = driver.poe_support_reason(port.port_number) if not poe_support_map[port.port_number] else ""
            poe_role_map[port.port_number] = driver.poe_role_for_port(port.port_number)
            poe_note_map[port.port_number] = driver.poe_note_for_port(port.port_number)
        poe_supported_count = len([port_number for port_number, supported in poe_support_map.items() if supported])
    if device and form.validate_on_submit():
        driver = get_driver(device)
        try:
            if not form.dry_run.data:
                driver.connect()
            if form.enabled.data and not driver.supports_poe_port(form.port_number.data):
                raise RuntimeError(driver.poe_support_reason(form.port_number.data) or "PoE wird auf diesem Port nicht unterstuetzt.")
            result = driver.set_poe_state(form.port_number.data, form.enabled.data, dry_run=form.dry_run.data)
            preview = result
            if not form.dry_run.data:
                port = Port.query.filter_by(device_id=device.id, port_number=form.port_number.data).first()
                if port:
                    port.poe_enabled = form.enabled.data
                    db.session.commit()
            flash("PoE Vorschau erstellt." if form.dry_run.data else "PoE angewendet.", "success")
            write_audit(current_user.username, "poe_update", device.name, str(result["commands"]), "success")
        except Exception as exc:  # noqa: BLE001
            flash(str(exc), "error")
            write_audit(current_user.username, "poe_update", device.name, "PoE fehlgeschlagen", "failed", str(exc))
        finally:
            driver.close()
    return render_template(
        "poe/index.html",
        form=form,
        ports=ports,
        preview=preview,
        device=device,
        poe_support_map=poe_support_map,
        poe_reason_map=poe_reason_map,
        poe_role_map=poe_role_map,
        poe_note_map=poe_note_map,
        poe_supported_count=poe_supported_count,
    )
