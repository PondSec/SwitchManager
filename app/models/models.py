from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="operator", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))


class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    host = db.Column(db.String(128), nullable=False)
    ssh_port = db.Column(db.Integer, default=22, nullable=False)
    username = db.Column(db.String(128), nullable=False)
    password = db.Column(db.String(255), nullable=True)
    key_path = db.Column(db.String(255), nullable=True)
    model = db.Column(db.String(120), default="Unbekannt")
    firmware = db.Column(db.String(120), default="Unbekannt")
    mgmt_ip = db.Column(db.String(64), default="-")
    last_seen_at = db.Column(db.DateTime)
    status = db.Column(db.String(32), default="unknown")
    driver_type = db.Column(db.String(64), default="zyxel-ssh")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class VLAN(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("device.id"), nullable=False)
    vlan_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Port(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("device.id"), nullable=False)
    port_number = db.Column(db.Integer, nullable=False)
    alias = db.Column(db.String(120), default="")
    admin_enabled = db.Column(db.Boolean, default=True)
    link_state = db.Column(db.String(20), default="down")
    speed = db.Column(db.String(20), default="-")
    duplex = db.Column(db.String(20), default="-")
    vlan_mode = db.Column(db.String(20), default="untagged")
    vlan_id = db.Column(db.Integer, default=1)
    poe_enabled = db.Column(db.Boolean, default=False)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(120), nullable=False)
    target = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text, nullable=False)
    result = db.Column(db.String(20), nullable=False)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class NetworkProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    purpose = db.Column(db.String(40), nullable=False, default="corporate")
    vlan_id = db.Column(db.Integer, nullable=False)
    gateway_ip = db.Column(db.String(64), nullable=False)
    subnet_mask = db.Column(db.String(64), nullable=False)
    dhcp_enabled = db.Column(db.Boolean, default=True)
    dhcp_start = db.Column(db.String(64))
    dhcp_end = db.Column(db.String(64))
    dhcp_lease_time = db.Column(db.Integer, default=86400)
    dns_primary = db.Column(db.String(64))
    dns_secondary = db.Column(db.String(64))
    igmp_snooping = db.Column(db.Boolean, default=False)
    dhcp_guarding = db.Column(db.Boolean, default=False)
    upnp_lan = db.Column(db.Boolean, default=False)
    multicast_dns = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
