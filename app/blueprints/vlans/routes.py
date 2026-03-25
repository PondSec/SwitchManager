from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.network_forms import VLANForm
from app.models.models import Device, VLAN
from app.services.audit_service import write_audit
from app.services.device_inventory import apply_vlan_snapshot
from app.utils.device_context import get_selected_device
from app.utils.driver_factory import get_driver

bp = Blueprint("vlans", __name__, url_prefix="/vlans")


def _load_live_vlans(device) -> list[dict]:
    driver = get_driver(device)
    try:
        driver.connect()
        vlans = driver.get_vlans()
        apply_vlan_snapshot(device, vlans)
        return vlans
    finally:
        driver.close()


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    form = VLANForm()
    preview = None
    selected_device = get_selected_device()
    live_vlans: list[dict] = []

    if selected_device and request.method == "GET":
        try:
            live_vlans = _load_live_vlans(selected_device)
        except Exception:  # noqa: BLE001
            live_vlans = []

    if form.validate_on_submit() and selected_device:
        driver = get_driver(selected_device)
        try:
            if not form.dry_run.data and selected_device.driver_type != "zyxel-ssh":
                driver.connect()
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

    vlans = VLAN.query.filter_by(device_id=selected_device.id).order_by(VLAN.vlan_id.asc()).all() if selected_device else []
    return render_template("vlans/index.html", form=form, vlans=vlans, live_vlans=live_vlans, preview=preview, device=selected_device)


@bp.route("/<int:vlan_db_id>/delete", methods=["POST"])
@login_required
def delete(vlan_db_id: int):
    selected_device = get_selected_device()
    vlan = VLAN.query.get_or_404(vlan_db_id)
    if not selected_device or vlan.device_id != selected_device.id:
        flash("VLAN gehört nicht zum aktuell ausgewählten Gerät.", "error")
        return redirect(url_for("vlans.index"))
    if vlan.vlan_id == 1:
        flash("Default-VLAN 1 wird nicht gelöscht.", "error")
        return redirect(url_for("vlans.index"))

    driver = get_driver(selected_device)
    try:
        if selected_device.driver_type != "zyxel-ssh":
            driver.connect()
        driver.delete_vlan(vlan.vlan_id, dry_run=False)
        write_audit(current_user.username, "vlan_delete", selected_device.name, f"VLAN {vlan.vlan_id} gelöscht", "success")
        db.session.delete(vlan)
        db.session.commit()
        flash(f"VLAN {vlan.vlan_id} gelöscht.", "success")
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        write_audit(current_user.username, "vlan_delete", selected_device.name, "VLAN-Löschung fehlgeschlagen", "failed", str(exc))
        flash(str(exc), "error")
    finally:
        driver.close()
    return redirect(url_for("vlans.index"))
