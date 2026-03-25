from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.device_forms import DeviceForm
from app.models.models import Device
from app.services.audit_service import write_audit
from app.utils.driver_factory import get_driver

bp = Blueprint("devices", __name__, url_prefix="/devices")


@bp.route("/")
@login_required
def index():
    return render_template("devices/index.html", devices=Device.query.order_by(Device.name.asc()).all())


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
            key_path=form.key_path.data,
            driver_type=form.driver_type.data,
        )
        db.session.add(device)
        db.session.commit()
        write_audit(current_user.username, "device_create", device.name, f"Device {device.host} erstellt", "success")
        flash("Gerät gespeichert.", "success")
        return redirect(url_for("devices.index"))
    return render_template("devices/form.html", form=form, title="Gerät hinzufügen")


@bp.route("/<int:device_id>/edit", methods=["GET", "POST"])
@login_required
def edit(device_id: int):
    device = Device.query.get_or_404(device_id)
    form = DeviceForm(obj=device)
    if form.validate_on_submit():
        form.populate_obj(device)
        db.session.commit()
        write_audit(current_user.username, "device_edit", device.name, "Gerät bearbeitet", "success")
        flash("Gerät aktualisiert.", "success")
        return redirect(url_for("devices.index"))
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
