from app.extensions import db
from app.models.models import Device, Port, User, VLAN


def ensure_seed_data() -> None:
    if not User.query.filter_by(username="admin").first():
        user = User(username="admin", role="admin")
        user.set_password("admin12345")
        db.session.add(user)

    device = Device.query.filter_by(name="Core-Switch").first()
    if not device:
        device = Device(
            name="Core-Switch",
            host="192.168.1.10",
            ssh_port=22,
            username="admin",
            password="",
            model="GS-Serie",
            firmware="n/a",
            status="unknown",
        )
        db.session.add(device)
        db.session.flush()
        for i in range(1, 25):
            db.session.add(Port(device_id=device.id, port_number=i, link_state="up" if i % 3 == 0 else "down"))
        db.session.add(VLAN(device_id=device.id, vlan_id=1, name="Default"))
    db.session.commit()
