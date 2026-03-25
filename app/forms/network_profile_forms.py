from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, IPAddress, Length, NumberRange, Optional


class NetworkProfileForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(min=2, max=120)])
    purpose = SelectField(
        "Zweck",
        choices=[("corporate", "Corporate"), ("guest", "Guest"), ("iot", "IoT"), ("voice", "Voice")],
    )
    vlan_id = IntegerField("VLAN", validators=[DataRequired(), NumberRange(min=1, max=4094)])
    gateway_ip = StringField("Gateway IP", validators=[DataRequired(), IPAddress(ipv4=True, ipv6=False)])
    subnet_mask = StringField("Subnetzmaske", validators=[DataRequired(), Length(min=7, max=15)], default="255.255.255.0")
    dhcp_enabled = BooleanField("DHCP aktiv", default=True)
    dhcp_start = StringField("DHCP Start", validators=[Optional(), IPAddress(ipv4=True, ipv6=False)])
    dhcp_end = StringField("DHCP Ende", validators=[Optional(), IPAddress(ipv4=True, ipv6=False)])
    dhcp_lease_time = IntegerField("Lease Time", validators=[DataRequired(), NumberRange(min=60, max=604800)], default=86400)
    dns_primary = StringField("DNS 1", validators=[Optional(), IPAddress(ipv4=True, ipv6=False)])
    dns_secondary = StringField("DNS 2", validators=[Optional(), IPAddress(ipv4=True, ipv6=False)])
    igmp_snooping = BooleanField("IGMP Snooping")
    dhcp_guarding = BooleanField("DHCP Guarding")
    upnp_lan = BooleanField("UPnP LAN")
    multicast_dns = BooleanField("mDNS")
    submit = SubmitField("Profil speichern")
