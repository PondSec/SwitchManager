from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.forms.auth_forms import LoginForm, UserCreateForm
from app.models.models import User
from app.services.audit_service import write_audit

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            write_audit(user.username, "login", "webapp", "Erfolgreiche Anmeldung", "success")
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("Ungültige Zugangsdaten", "error")
    return render_template("auth/login.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    write_audit(current_user.username, "logout", "webapp", "Abmeldung", "success")
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/users", methods=["GET", "POST"])
@login_required
def users():
    if current_user.role != "admin":
        flash("Nur Admin darf Benutzer verwalten.", "error")
        return redirect(url_for("dashboard.index"))
    form = UserCreateForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("Benutzername existiert bereits.", "error")
        else:
            user = User(username=form.username.data, role=form.role.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            write_audit(current_user.username, "user_create", form.username.data, "Neuer Benutzer", "success")
            flash("Benutzer erstellt.", "success")
            return redirect(url_for("auth.users"))
    return render_template("settings/users.html", form=form, users=User.query.order_by(User.created_at.desc()).all())
