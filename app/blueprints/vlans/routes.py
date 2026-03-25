from flask import Blueprint, flash, render_template
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.network_forms import VLANForm
from app.models.models import Device, VLAN
from app.services.audit_service import write_audit
from app.utils.driver_factory import get_driver

bp = Blueprint("vlans", __name__, url_prefix="/vlans")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = VLANForm()
    preview = None
    devices = Device.query.order_by(Device.name.asc()).all()
    selected_device = devices[0] if devices else None

    if form.validate_on_submit() and selected_device:
        driver = get_driver(selected_device)
        try:
            result = driver.create_vlan(form.vlan_id.data, form.name.data, dry_run=form.dry_run.data)
            preview = result
            if not form.dry_run.data:
                db.session.add(VLAN(device_id=selected_device.id, vlan_id=form.vlan_id.data, name=form.name.data))
                db.session.commit()
                flash("VLAN angewendet.", "success")
            else:
                flash("Vorschau erstellt. Noch nicht angewendet.", "info")
            write_audit(current_user.username, "vlan_create", selected_device.name, str(result["commands"]), "success")
        except Exception as exc:  # noqa: BLE001
            flash(str(exc), "error")
            write_audit(current_user.username, "vlan_create", selected_device.name, "Fehler beim VLAN", "failed", str(exc))
        finally:
            driver.close()

    vlans = VLAN.query.order_by(VLAN.vlan_id.asc()).all()
    return render_template("vlans/index.html", form=form, vlans=vlans, preview=preview, device=selected_device)
