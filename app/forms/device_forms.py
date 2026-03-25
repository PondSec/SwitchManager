from flask_wtf import FlaskForm
from wtforms import IntegerField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, IPAddress, Length, NumberRange, Optional


class DeviceForm(FlaskForm):
    name = StringField("Gerätename", validators=[DataRequired(), Length(min=2, max=120)])
    host = StringField("Host / IP", validators=[DataRequired(), IPAddress(ipv4=True, ipv6=False)])
    ssh_port = IntegerField("SSH-Port", validators=[DataRequired(), NumberRange(min=1, max=65535)], default=22)
    username = StringField("SSH-Benutzer", validators=[DataRequired(), Length(min=1, max=128)])
    password = PasswordField("SSH-Passwort", validators=[Optional(), Length(max=255)])
    key_path = StringField("SSH-Key Pfad (optional)", validators=[Optional(), Length(max=255)])
    model = StringField("Modell", validators=[Optional(), Length(max=120)])
    inventory_port_count = IntegerField("Port-Anzahl (Fallback)", validators=[Optional(), NumberRange(min=1, max=128)])
    driver_type = SelectField("Treiber", choices=[("zyxel-ssh", "Zyxel SSH"), ("edgeos-ssh", "EdgeOS SSH (EdgeRouter)")])
    submit = SubmitField("Speichern")
