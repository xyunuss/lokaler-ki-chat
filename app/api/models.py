"""Model discovery."""

from __future__ import annotations

from flask import Blueprint, jsonify

from app import current_client

bp = Blueprint("models", __name__, url_prefix="/api")


@bp.get("/models")
def list_models():
    """Locally installed models, with size and quantization."""
    models = current_client().list_models()
    return jsonify({"models": [model.to_dict() for model in models]})
