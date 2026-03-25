from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class LoginForm(FlaskForm):
    username = StringField("Benutzername", validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField("Passwort", validators=[DataRequired(), Length(min=6, max=128)])
    submit = SubmitField("Anmelden")


class UserCreateForm(FlaskForm):
    username = StringField("Benutzername", validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField("Passwort", validators=[DataRequired(), Length(min=8, max=128)])
    role = SelectField("Rolle", choices=[("admin", "Admin"), ("operator", "Operator"), ("readonly", "Read-Only")])
    submit = SubmitField("Benutzer anlegen")
