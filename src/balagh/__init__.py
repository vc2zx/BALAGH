"""BALAGH community issue triage package."""

from __future__ import annotations

import os
import hmac
import secrets
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask


__version__ = "3.0.0"

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(test_config: dict[str, Any] | None = None) -> "Flask":
    """Create the Flask application and register citizen and staff routes."""
    from dotenv import load_dotenv
    from flask import Flask, abort, redirect, request, session, url_for
    from werkzeug.middleware.proxy_fix import ProxyFix

    load_dotenv()

    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-development-only"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("BALAGH_REQUIRE_HTTPS", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        RATE_LIMIT_ENABLED=True,
        REQUIRE_HTTPS=os.getenv("BALAGH_REQUIRE_HTTPS", "0") == "1",
    )

    if test_config:
        app.config.update(test_config)
    trusted_proxies = int(os.getenv("BALAGH_TRUSTED_PROXY_COUNT", "0"))
    if trusted_proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=trusted_proxies, x_host=trusted_proxies)
    app.config.setdefault("CSRF_ENABLED", not app.testing)
    if not app.testing and app.secret_key in {"local-development-only", "change-this-local-secret", ""}:
        raise RuntimeError("Set a unique FLASK_SECRET_KEY in .env before starting BALAGH.")

    @app.context_processor
    def csrf_template_token() -> dict[str, str]:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["csrf_token"]}

    @app.before_request
    def protect_forms():
        if app.config["REQUIRE_HTTPS"] and not request.is_secure and request.path not in {"/health/live", "/health/ready"}:
            abort(403, description="HTTPS is required")
        if request.method == "POST" and app.config["CSRF_ENABLED"]:
            expected = session.get("csrf_token", "")
            submitted = request.form.get("_csrf_token", "")
            if not expected or not hmac.compare_digest(expected, submitted):
                abort(400, description="انتهت صلاحية النموذج. حدّث الصفحة وحاول مرة أخرى.")

    from balagh import database
    from balagh.citizen_routes import citizen_bp
    from balagh.staff_routes import staff_bp

    database.init_db()
    app.register_blueprint(citizen_bp)
    app.register_blueprint(staff_bp)

    @app.get("/")
    def index():
        return redirect(url_for("citizen.home"))

    @app.get("/health/live")
    def live():
        return {"status": "live"}

    @app.get("/health/ready")
    def ready():
        try:
            with database._connection() as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                connection.execute("SELECT 1 FROM triage_jobs LIMIT 1")
            if version != 3:
                raise RuntimeError("schema version mismatch")
        except Exception:
            return {"status": "not_ready"}, 503
        return {"status": "ready", "schema_version": version}

    return app
