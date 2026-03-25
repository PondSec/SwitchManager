from flask import Blueprint, render_template, request
from flask_login import login_required

from app.models.models import AuditLog

bp = Blueprint("audit", __name__, url_prefix="/audit")


@bp.route("/")
@login_required
def index():
    query = AuditLog.query
    username = request.args.get("username")
    result = request.args.get("result")
    if username:
        query = query.filter(AuditLog.username == username)
    if result:
        query = query.filter(AuditLog.result == result)
    logs = query.order_by(AuditLog.created_at.desc()).limit(300).all()
    return render_template("audit/index.html", logs=logs)
