from app.extensions import db
from app.models.models import Device, NetworkProfile, Port, User, VLAN


def ensure_seed_data() -> None:
    if not User.query.filter_by(username="admin").first():
        user = User(username="admin", role="admin")
        user.set_password("admin12345")
        db.session.add(user)

    sample_device = Device.query.filter_by(
        name="Core-Switch",
        host="192.168.1.10",
        username="admin",
        model="GS-Serie",
    ).first()
    if sample_device:
        Port.query.filter_by(device_id=sample_device.id).delete()
        VLAN.query.filter_by(device_id=sample_device.id).delete()
        db.session.delete(sample_device)

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
