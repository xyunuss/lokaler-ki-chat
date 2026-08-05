"""Application factory.

Keeping the app behind a factory means tests can build an isolated instance
with its own configuration instead of importing a module-level singleton.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, current_app, jsonify, render_template

from app.config import Config
from app.ollama import OllamaClient, OllamaError
from app.storage import Store

__version__ = "2.0.0"

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app(config: Config | None = None) -> Flask:
    # The UI is served by Flask, so it is same-origin with the API. Opening
    # index.html from disk is what forced the old build to enable CORS for
    # every origin.
    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / "static"),
        template_folder=str(BASE_DIR / "templates"),
    )
    cfg = config or Config.from_env()
    app.config["APP_CONFIG"] = cfg
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_upload_bytes

    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    # One client per app: it keeps a connection pool alive across requests.
    app.config["OLLAMA_CLIENT"] = OllamaClient(
        base_url=cfg.ollama_url,
        connect_timeout=cfg.connect_timeout,
        request_timeout=cfg.request_timeout,
    )
    app.config["STORE"] = Store(cfg.data_dir / "chat.db")

    from app.api.chat import bp as chat_bp
    from app.api.conversations import bp as conversations_bp
    from app.api.documents import bp as documents_bp
    from app.api.health import bp as health_bp
    from app.api.models import bp as models_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(models_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(conversations_bp)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.errorhandler(OllamaError)
    def _handle_ollama_error(exc: OllamaError):
        """Turn transport failures into a response the UI can explain."""
        return jsonify(exc.to_dict()), exc.status

    return app


def current_config() -> Config:
    """Config of the app handling the current request."""
    return current_app.config["APP_CONFIG"]


def current_client() -> OllamaClient:
    """Ollama client of the app handling the current request."""
    return current_app.config["OLLAMA_CLIENT"]


def current_store() -> Store:
    """Conversation store of the app handling the current request."""
    return current_app.config["STORE"]
