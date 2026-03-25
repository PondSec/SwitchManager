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
    driver_type = SelectField("Treiber", choices=[("zyxel-ssh", "Zyxel SSH (vorbereitet)")])
    submit = SubmitField("Speichern")
