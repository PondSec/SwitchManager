from flask import Blueprint, render_template
from flask_login import login_required

from app.models.models import AuditLog, Device, VLAN

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    devices = Device.query.order_by(Device.name.asc()).all()
    stats = {
        "devices": len(devices),
        "online": len([d for d in devices if d.status == "online"]),
        "vlans": VLAN.query.count(),
        "changes": AuditLog.query.count(),
    }
    recent = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all()
    return render_template("dashboard/index.html", devices=devices, stats=stats, recent=recent)
