"""Chat endpoint.

The response is a stream of newline-delimited JSON events rather than raw
text, because raw text cannot carry anything besides the answer: no timings,
no end marker, and no way to report a failure that happens mid-generation
(the old code appended "[Error: ...]" into the middle of the reply).

    {"type": "start", "conversationId": "...", "title": "..."}
    {"type": "token", "content": "Hel"}
    {"type": "done",  "messageId": 12, "stats": {...}}
    {"type": "error", "error": "...", "hint": "..."}
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app import current_client, current_store
from app.ollama import DoneEvent, OllamaError, TokenEvent
from app.storage import derive_title

bp = Blueprint("chat", __name__, url_prefix="/api")

MAX_MESSAGE_CHARS = 200_000

# Only these are forwarded to Ollama - anything else a client sends is ignored.
ALLOWED_OPTIONS = {"temperature", "top_p", "top_k", "num_ctx", "seed", "repeat_penalty"}


def _event(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _clean_options(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if key in ALLOWED_OPTIONS and isinstance(value, (int, float))
    }


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
            messages.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    return messages


def _compose_user_content(text: str, attachments: list[dict[str, Any]]) -> str:
    """Message text plus the extracted document sections."""
    sections = [
        attachment["promptSection"]
        for attachment in attachments
        if isinstance(attachment.get("promptSection"), str)
    ]
    if not sections:
        return text
    joined = "\n\n".join(sections)
    return f"{text}\n\n{joined}" if text else joined


def _stream(model: str, messages: list[dict[str, str]], options: dict[str, Any], *, prelude=None,
            on_done=None, on_partial=None) -> Response:
    """Run a generation and stream it as NDJSON.

    The first event is pulled before the response starts, so an unreachable
    Ollama still produces a proper HTTP error instead of a 200 with the error
    buried in the body.
    """
    events = current_client().chat(model, messages, options=options or None)
    first = next(events, None)

    def generate() -> Iterator[str]:
        collected: list[str] = []
        completed = False
        try:
            if prelude:
                yield _event(prelude)

            for event in _chain(first, events):
                if isinstance(event, TokenEvent):
                    collected.append(event.content)
                    yield _event({"type": "token", "content": event.content})
                elif isinstance(event, DoneEvent):
                    completed = True
                    extra = on_done("".join(collected), event.stats.to_dict()) if on_done else {}
                    yield _event(
                        {
                            "type": "done",
                            "reason": event.reason,
                            "stats": event.stats.to_dict(),
                            **(extra or {}),
                        }
                    )
        except OllamaError as exc:
            yield _event({"type": "error", **exc.to_dict()})
        finally:
            # Reached when the client disconnects mid-stream (stop button):
            # keep whatever was generated so the transcript is not lost.
            if not completed and collected and on_partial:
                on_partial("".join(collected))

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

    options = _clean_options(data.get("options"))
    conversation_id = data.get("conversationId")

    if isinstance(conversation_id, str) and conversation_id:
        return _conversation_turn(conversation_id, model, options, data)

    # Stateless mode: the caller supplies the whole transcript and nothing is
    # persisted. Handy for scripting against the API.
    messages = _clean_messages(data.get("messages"))
    system = data.get("system")
    if isinstance(system, str) and system.strip():
        messages = [{"role": "system", "content": system.strip()}, *messages]
    if not messages:
        return jsonify({"error": "At least one message is required."}), 400

    return _stream(model, messages, options)


def _conversation_turn(conversation_id: str, model: str, options: dict[str, Any], data: dict):
    """A turn inside a stored conversation: persist, stream, persist."""
    store = current_store()
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        return jsonify({"error": "Conversation not found."}), 404

    regenerate = bool(data.get("regenerate"))
    attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
    text = data.get("content") if isinstance(data.get("content"), str) else ""
    text = text.strip()[:MAX_MESSAGE_CHARS]

    prelude: dict[str, Any] = {"type": "start", "conversationId": conversation_id}

    if regenerate:
        store.drop_trailing_assistant(conversation_id)
    else:
        if not text and not attachments:
            return jsonify({"error": "Message is empty."}), 400

        user_message = store.add_message(
            conversation_id,
            "user",
            _compose_user_content(text, attachments),
            attachments=[
                {key: attachment.get(key) for key in ("name", "kind", "chars", "pages")}
                for attachment in attachments
            ]
            or None,
        )
        prelude["userMessageId"] = user_message.id

        # First real message names the conversation.
        if conversation.title in {"New chat", ""} and text:
            title = derive_title(text)
            store.update_conversation(conversation_id, title=title)
            prelude["title"] = title

    if conversation.model != model:
        store.update_conversation(conversation_id, model=model)

    history = [message.to_chat_turn() for message in store.list_messages(conversation_id)]
    if not history:
        return jsonify({"error": "Nothing to send."}), 400
    if conversation.system_prompt:
        history = [{"role": "system", "content": conversation.system_prompt}, *history]

    def persist(content: str, stats: dict | None = None) -> dict[str, Any]:
        message = store.add_message(conversation_id, "assistant", content, stats=stats)
        return {"messageId": message.id}

    return _stream(
        model,
        history,
        options,
        prelude=prelude,
        on_done=persist,
        on_partial=lambda content: persist(content, {"cancelled": True}),
    )
