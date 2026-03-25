from flask import Blueprint, render_template
from flask_login import login_required

from app.models.models import User

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/")
@login_required
def index():
    return render_template("settings/index.html", users=User.query.order_by(User.username.asc()).all())
