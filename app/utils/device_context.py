from flask import session

from app.models.models import Device


def get_selected_device() -> Device | None:
    selected_id = session.get("selected_device_id")
    if selected_id:
        device = Device.query.get(selected_id)
        if device:
            return device
    return Device.query.order_by(Device.id.asc()).first()


def set_selected_device(device_id: int) -> None:
    session["selected_device_id"] = device_id
