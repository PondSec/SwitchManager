from collections import Counter, deque
from pathlib import Path

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

    log_path = Path("logs") / "switchmanager.log"
    controller_log = []
    if log_path.exists():
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            controller_log = list(deque(handle, maxlen=200))

    action_counts = Counter(log.action for log in logs)
    summary = {
        "total": len(logs),
        "success": len([log for log in logs if log.result == "success"]),
        "failed": len([log for log in logs if log.result == "failed"]),
        "actors": len({log.username for log in logs}),
        "controller_lines": len(controller_log),
    }

    return render_template(
        "audit/index.html",
        logs=logs,
        controller_log=controller_log,
        filters={"username": username or "", "result": result or ""},
        summary=summary,
        action_summary=action_counts.most_common(6),
    )
