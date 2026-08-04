"""Model discovery and downloads."""

from __future__ import annotations

import json
from collections.abc import Iterator

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app import current_client
from app.ollama import OllamaError

bp = Blueprint("models", __name__, url_prefix="/api/models")


@bp.get("")
def list_models():
    """Locally installed models, with size and quantization."""
    models = current_client().list_models()
    return jsonify({"models": [model.to_dict() for model in models]})


@bp.post("/pull")
def pull_model():
    """Download a model, streaming progress as NDJSON.

    Previously the only way to add a model was to leave the app, run
    `ollama pull` in a terminal and reload the page.
    """
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return jsonify({"error": "A model name is required."}), 400

    events = current_client().pull(name.strip())
    first = next(events, None)

    def generate() -> Iterator[str]:
        try:
            for event in ([first] if first else []) + list(events):
                yield json.dumps({"type": "progress", **event.to_dict()}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
        except OllamaError as exc:
            yield json.dumps({"type": "error", **exc.to_dict()}) + "\n"

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@bp.get("/<path:name>")
def show_model(name: str):
    """Details Ollama knows about a model (family, parameters, template)."""
    details = current_client().show(name)
    return jsonify(
        {
            "name": name,
            "details": details.get("details") or {},
            "parameters": details.get("parameters"),
            "template": details.get("template"),
        }
    )
