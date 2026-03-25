from flask import Blueprint, render_template
from flask_login import login_required

from app.models.models import AuditLog, Device, Port, VLAN

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    devices = Device.query.order_by(Device.name.asc()).all()
    ports = Port.query.all()
    online_devices = [d for d in devices if d.status == "online"]
    offline_devices = [d for d in devices if d.status == "offline"]
    active_ports = [p for p in ports if p.link_state == "up" and p.admin_enabled]
    disabled_ports = [p for p in ports if not p.admin_enabled]
    warnings = [p for p in ports if p.link_state == "down" and p.admin_enabled]

    stats = {
        "devices_total": len(devices),
        "devices_online": len(online_devices),
        "devices_offline": len(offline_devices),
        "ports_total": len(ports),
        "ports_active": len(active_ports),
        "ports_disabled": len(disabled_ports),
        "warnings": len(warnings),
        "vlans": VLAN.query.count(),
        "changes": AuditLog.query.count(),
    }

    device_health = []
    for device in devices:
        device_ports = [p for p in ports if p.device_id == device.id]
        uplinks = [p for p in device_ports if p.link_state == "up"]
        down_count = len([p for p in device_ports if p.link_state == "down" and p.admin_enabled])
        device_health.append(
            {
                "device": device,
                "ports_total": len(device_ports),
                "ports_up": len(uplinks),
                "warnings": down_count,
            }
        )

    problematic = sorted(device_health, key=lambda item: item["warnings"], reverse=True)[:5]
    recent = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(20).all()

    return render_template(
        "dashboard/index.html",
        stats=stats,
        recent=recent,
        device_health=device_health,
        problematic=problematic,
    )
