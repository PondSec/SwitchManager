from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class VLANForm(FlaskForm):
    vlan_id = IntegerField("VLAN-ID", validators=[DataRequired(), NumberRange(min=1, max=4094)])
    name = StringField("VLAN-Name", validators=[DataRequired(), Length(min=2, max=120)])
    dry_run = BooleanField("Nur Vorschau (Dry Run)", default=True)
    submit = SubmitField("VLAN erstellen")


class PortConfigForm(FlaskForm):
    port_number = IntegerField("Port", validators=[DataRequired(), NumberRange(min=1, max=48)])
    admin_enabled = BooleanField("Port aktiv", default=True)
    vlan_id = IntegerField("VLAN-ID", validators=[DataRequired(), NumberRange(min=1, max=4094)])
    vlan_mode = SelectField(
        "VLAN-Modus",
        choices=[("tagged", "Tagged"), ("untagged", "Untagged"), ("excluded", "Excluded")],
    )
    alias = StringField("Alias", validators=[Optional(), Length(max=120)])
    dry_run = BooleanField("Nur Vorschau (Dry Run)", default=True)
    submit = SubmitField("Port anwenden")


class BulkPortForm(FlaskForm):
    ports = StringField("Ports (z.B. 1,2,3)", validators=[DataRequired(), Length(max=120)])
    admin_enabled = BooleanField("Ports aktivieren", default=True)
    dry_run = BooleanField("Nur Vorschau (Dry Run)", default=True)
    submit = SubmitField("Bulk anwenden")


class PoEForm(FlaskForm):
    port_number = IntegerField("PoE Port", validators=[DataRequired(), NumberRange(min=1, max=48)])
    enabled = BooleanField("PoE aktivieren")
    dry_run = BooleanField("Nur Vorschau (Dry Run)", default=True)
    submit = SubmitField("PoE anwenden")
