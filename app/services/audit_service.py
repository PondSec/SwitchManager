from flask import current_app

from app.extensions import db
from app.models.models import AuditLog


def write_audit(username: str, action: str, target: str, details: str, result: str, error_message: str | None = None) -> None:
    db.session.add(
        AuditLog(
            username=username,
            action=action,
            target=target,
            details=details,
            result=result,
            error_message=error_message,
        )
    )
    db.session.commit()
    current_app.logger.info("AUDIT user=%s action=%s target=%s result=%s", username, action, target, result)
