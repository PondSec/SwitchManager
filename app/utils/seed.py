from app.extensions import db
from app.models.models import Device, NetworkProfile, Port, User, VLAN


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
    if not NetworkProfile.query.filter_by(name="LAN-Default").first():
        db.session.add(NetworkProfile(
            name="LAN-Default",
            purpose="corporate",
            vlan_id=1,
            gateway_ip="192.168.1.1",
            subnet_mask="255.255.255.0",
            dhcp_enabled=True,
            dhcp_start="192.168.1.20",
            dhcp_end="192.168.1.254",
            dhcp_lease_time=86400,
            dns_primary="1.1.1.1",
            dns_secondary="8.8.8.8",
        ))
    db.session.commit()
