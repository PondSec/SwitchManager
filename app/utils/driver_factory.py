from app.models.models import Device
from app.services.zyxel_driver import ZyxelSSHDriver


def get_driver(device: Device):
    if device.driver_type == "zyxel-ssh":
        return ZyxelSSHDriver(device.host, device.ssh_port, device.username, device.password, device.key_path)
    raise ValueError(f"Unbekannter Treiber: {device.driver_type}")
