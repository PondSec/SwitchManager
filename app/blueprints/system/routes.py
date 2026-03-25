from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models.models import Device
from app.services.audit_service import write_audit
from app.utils.device_context import get_selected_device
from app.utils.driver_factory import get_driver

bp = Blueprint("system", __name__, url_prefix="/system")


@bp.route("/")
@login_required
def index():
    return render_template("system/index.html", device=Device.query.first())


@bp.route("/action/<string:action>", methods=["POST"])
@login_required
def action(action: str):
    device = get_selected_device()
    if not device:
        flash("Kein Gerät verfügbar.", "error")
        return redirect(url_for("system.index"))

    dry_run = request.form.get("dry_run", "1") == "1"
    driver = get_driver(device)
    result = None
    try:
        if action == "backup":
            result = driver.backup_config(dry_run=dry_run)
        elif action == "save":
            result = driver.save_config(dry_run=dry_run)
        elif action == "reboot":
            result = driver.reboot_device(dry_run=dry_run)
        else:
            flash("Unbekannte Aktion.", "error")
            return redirect(url_for("system.index"))
        flash("Systemaktion als Vorschau erstellt." if dry_run else "Systemaktion ausgeführt.", "success")
        write_audit(current_user.username, f"system_{action}", device.name, str(result["commands"]), "success")
    except Exception as exc:  # noqa: BLE001
        flash(str(exc), "error")
        write_audit(current_user.username, f"system_{action}", device.name, "Systemaktion fehlgeschlagen", "failed", str(exc))
    finally:
        driver.close()
    return render_template("system/index.html", device=device, result=result)
