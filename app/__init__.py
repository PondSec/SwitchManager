import logging
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from config import Config
from .extensions import csrf, db, login_manager

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    _configure_logging(app)
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    from .models import models  # noqa: F401

    with app.app_context():
        db.create_all()
        from .utils.seed import ensure_seed_data

        ensure_seed_data()

    _register_blueprints(app)
    _register_context(app)
    return app


def _configure_logging(app: Flask) -> None:
    log_path = Path("logs")
    log_path.mkdir(exist_ok=True)
    handler = logging.FileHandler(log_path / "switchmanager.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def _register_blueprints(app: Flask) -> None:
    from .blueprints.audit.routes import bp as audit_bp
    from .blueprints.auth.routes import bp as auth_bp
    from .blueprints.dashboard.routes import bp as dashboard_bp
    from .blueprints.devices.routes import bp as devices_bp
    from .blueprints.health.routes import bp as health_bp
    from .blueprints.networks.routes import bp as networks_bp
    from .blueprints.poe.routes import bp as poe_bp
    from .blueprints.ports.routes import bp as ports_bp
    from .blueprints.settings.routes import bp as settings_bp
    from .blueprints.system.routes import bp as system_bp
    from .blueprints.vlans.routes import bp as vlans_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(networks_bp)
    app.register_blueprint(vlans_bp)
    app.register_blueprint(ports_bp)
    app.register_blueprint(poe_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(health_bp)


def _register_context(app: Flask) -> None:
    from .models.models import Device

    @app.context_processor
    def inject_device_context():
        return {"all_devices": Device.query.order_by(Device.name.asc()).all()}
