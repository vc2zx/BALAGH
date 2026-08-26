"""BALAGH community issue triage package."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask


__version__ = "1.2.2"

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(test_config: dict[str, Any] | None = None) -> "Flask":
    """Create the Flask application and register citizen and staff routes."""
    from dotenv import load_dotenv
    from flask import Flask, redirect, url_for

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
