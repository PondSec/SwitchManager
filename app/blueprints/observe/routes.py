from flask import Blueprint, render_template
from flask_login import login_required

from app.models.models import Device, Port
from app.services.device_center import load_device_center_snapshot
from app.utils.device_context import get_selected_device, set_selected_device

bp = Blueprint("observe", __name__, url_prefix="/observe")


def _fleet_cards() -> list[dict]:
    devices = Device.query.order_by(Device.name.asc()).all()
    ports = Port.query.all()
    cards: list[dict] = []
    for device in devices:
        device_ports = [port for port in ports if port.device_id == device.id]
        cards.append({
            "device": device,
            "ports_up": len([port for port in device_ports if port.link_state == "up" and port.admin_enabled]),
            "ports_total": len(device_ports),
            "clients_hint": len([port for port in device_ports if port.link_state == "up"]),
        })
    return cards


@bp.route("/")
@login_required
def index():
    device = get_selected_device()
    snapshot = load_device_center_snapshot(device) if device else None
    return render_template("observe/index.html", device=device, snapshot=snapshot, fleet_cards=_fleet_cards())


@bp.route("/<int:device_id>")
@login_required
def device(device_id: int):
    device = Device.query.get_or_404(device_id)
    set_selected_device(device.id)
    snapshot = load_device_center_snapshot(device)
    return render_template("observe/index.html", device=device, snapshot=snapshot, fleet_cards=_fleet_cards())
