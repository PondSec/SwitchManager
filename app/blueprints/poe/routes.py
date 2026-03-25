from flask import Blueprint, flash, render_template
from flask_login import current_user, login_required

from app.forms.network_forms import PoEForm
from app.models.models import Device, Port
from app.services.audit_service import write_audit
from app.utils.driver_factory import get_driver

bp = Blueprint("poe", __name__, url_prefix="/poe")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = PoEForm()
    preview = None
    device = Device.query.first()
    ports = Port.query.filter_by(device_id=device.id).order_by(Port.port_number.asc()).all() if device else []
    if device and form.validate_on_submit():
        driver = get_driver(device)
        try:
            result = driver.set_poe_state(form.port_number.data, form.enabled.data, dry_run=form.dry_run.data)
            preview = result
            flash("PoE Vorschau erstellt." if form.dry_run.data else "PoE angewendet.", "success")
            write_audit(current_user.username, "poe_update", device.name, str(result["commands"]), "success")
        except Exception as exc:  # noqa: BLE001
            flash(str(exc), "error")
            write_audit(current_user.username, "poe_update", device.name, "PoE fehlgeschlagen", "failed", str(exc))
        finally:
            driver.close()
    return render_template("poe/index.html", form=form, ports=ports, preview=preview)
