"""Application factory.

Keeping the app behind a factory means tests can build an isolated instance
with its own configuration instead of importing a module-level singleton.
"""

from __future__ import annotations

from flask import Flask

from app.config import Config

__version__ = "2.0.0"


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)
    app.config["APP_CONFIG"] = config or Config.from_env()

    cfg: Config = app.config["APP_CONFIG"]
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_upload_bytes

    from app.api.chat import bp as chat_bp
    from app.api.models import bp as models_bp

    app.register_blueprint(models_bp)
    app.register_blueprint(chat_bp)

    return app


def current_config() -> Config:
    """Config of the app handling the current request."""
    from flask import current_app

    return current_app.config["APP_CONFIG"]
