"""Chat endpoints.

The response is a stream of newline-delimited JSON events rather than raw
text, because raw text cannot carry anything besides the answer: no timings,
no end marker, and no way to report a failure that happens mid-generation
(the old code appended "[Error: ...]" into the middle of the reply).

    {"type": "token", "content": "Hel"}
    {"type": "done",  "stats": {...}}
    {"type": "error", "error": "...", "hint": "..."}
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app import current_client
from app.ollama import DoneEvent, OllamaError, TokenEvent

bp = Blueprint("chat", __name__, url_prefix="/api")

# Only these are forwarded to Ollama - anything else a client sends is ignored.
ALLOWED_OPTIONS = {"temperature", "top_p", "top_k", "num_ctx", "seed", "repeat_penalty"}


def _event(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _clean_options(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in ALLOWED_OPTIONS and isinstance(v, (int, float))}


def _clean_messages(raw: Any) -> list[dict[str, str]]:
    """Drop anything that is not a well-formed chat turn."""
    if not isinstance(raw, list):
        return []
    messages: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"system", "user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content})
    return messages


def _stream_response(model: str, messages: list[dict[str, str]], options: dict[str, Any]):
    """Run a generation and stream it as NDJSON.

    The first event is pulled here, before the response starts, so an
    unreachable Ollama still results in a proper HTTP error instead of a
    200 with an error buried in the body.
    """
    client = current_client()
    events = client.chat(model, messages, options=options or None)
    first = next(events, None)

    def generate() -> Iterator[str]:
        try:
            for event in _chain(first, events):
                if isinstance(event, TokenEvent):
                    yield _event({"type": "token", "content": event.content})
                elif isinstance(event, DoneEvent):
                    yield _event(
                        {"type": "done", "reason": event.reason, "stats": event.stats.to_dict()}
                    )
        except OllamaError as exc:
            yield _event({"type": "error", **exc.to_dict()})
        except GeneratorExit:
            # Client hit stop: closing the generator closes the upstream
            # request, which tells Ollama to stop generating.
            raise

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _chain(first, rest):
    if first is not None:
        yield first
    yield from rest


@bp.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}

    model = data.get("model")
    if not isinstance(model, str) or not model:
        return jsonify({"error": "A model is required."}), 400

    messages = _clean_messages(data.get("messages") or data.get("history"))
    system = data.get("system")
    if isinstance(system, str) and system.strip():
        messages = [{"role": "system", "content": system.strip()}, *messages]

    if not messages:
        return jsonify({"error": "At least one message is required."}), 400

    return _stream_response(model, messages, _clean_options(data.get("options")))
