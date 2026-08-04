"""Model discovery."""

from __future__ import annotations

import subprocess

from flask import Blueprint, jsonify

bp = Blueprint("models", __name__, url_prefix="/api")


@bp.get("/models")
def list_models():
    """Locally installed Ollama models."""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=False)
        lines = result.stdout.strip().split("\n")[1:]
        models = [line.split()[0] for line in lines if line.strip()]
        return jsonify({"models": models})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
