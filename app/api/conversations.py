"""Conversation CRUD, search and export."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from app import current_store

bp = Blueprint("conversations", __name__, url_prefix="/api/conversations")


def _string(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped[:limit] if stripped else None


@bp.get("")
def list_conversations():
    query = request.args.get("q", "").strip() or None
    conversations = current_store().list_conversations(query=query)
    return jsonify({"conversations": [c.to_dict() for c in conversations]})


@bp.post("")
def create_conversation():
    data = request.get_json(silent=True) or {}
    conversation = current_store().create_conversation(
        title=_string(data.get("title"), 200) or "New chat",
        model=_string(data.get("model"), 200),
        system_prompt=_string(data.get("systemPrompt"), 8000),
    )
    return jsonify(conversation.to_dict()), 201


@bp.get("/<conversation_id>")
def get_conversation(conversation_id: str):
    store = current_store()
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        return jsonify({"error": "Conversation not found."}), 404

    messages = store.list_messages(conversation_id)
    return jsonify({**conversation.to_dict(), "messages": [m.to_dict() for m in messages]})


@bp.patch("/<conversation_id>")
def update_conversation(conversation_id: str):
    data = request.get_json(silent=True) or {}
    fields = {}
    if "title" in data:
        fields["title"] = _string(data.get("title"), 200) or "New chat"
    if "model" in data:
        fields["model"] = _string(data.get("model"), 200)
    if "systemPrompt" in data:
        fields["system_prompt"] = _string(data.get("systemPrompt"), 8000)

    conversation = current_store().update_conversation(conversation_id, **fields)
    if not conversation:
        return jsonify({"error": "Conversation not found."}), 404
    return jsonify(conversation.to_dict())


@bp.delete("/<conversation_id>")
def delete_conversation(conversation_id: str):
    if not current_store().delete_conversation(conversation_id):
        return jsonify({"error": "Conversation not found."}), 404
    return jsonify({"deleted": True})


@bp.get("/<conversation_id>/export")
def export_conversation(conversation_id: str):
    """Markdown by default - readable anywhere, pastes into notes and issues."""
    store = current_store()
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        return jsonify({"error": "Conversation not found."}), 404

    if request.args.get("format") == "json":
        messages = store.list_messages(conversation_id)
        return jsonify({**conversation.to_dict(), "messages": [m.to_dict() for m in messages]})

    markdown = store.export_markdown(conversation_id) or ""
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "" for c in conversation.title).strip()
    filename = (safe_title or "conversation").replace(" ", "-").lower()

    return Response(
        markdown,
        mimetype="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
    )


@bp.delete("/<conversation_id>/messages/<int:message_id>")
def delete_from_message(conversation_id: str, message_id: int):
    """Drop a message and everything after it (used when editing a turn)."""
    removed = current_store().delete_messages_from(conversation_id, message_id)
    return jsonify({"removed": removed})
