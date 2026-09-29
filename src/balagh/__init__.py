"""BALAGH community issue triage package."""

from __future__ import annotations

import os
import hmac
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask


__version__ = "2.0.2"

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(test_config: dict[str, Any] | None = None) -> "Flask":
    """Create the Flask application and register citizen and staff routes."""
    from dotenv import load_dotenv
    from flask import Flask, abort, redirect, request, session, url_for

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
    )

    if test_config:
        app.config.update(test_config)
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

    return app
