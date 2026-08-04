"""Liveness and dependency status."""

from __future__ import annotations

from flask import Blueprint, jsonify

from app import __version__, current_client, current_config

bp = Blueprint("health", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    """Whether the app is up and whether it can reach Ollama.

    The UI polls this to tell "Ollama is not running" apart from "something
    went wrong", which the old version could not distinguish.
    """
    client = current_client()
    reachable = client.health()

    return jsonify(
        {
            "status": "ok",
            "version": __version__,
            "ollama": {
                "url": current_config().ollama_url,
                "reachable": reachable,
            },
        }
    ), (200 if reachable else 503)
