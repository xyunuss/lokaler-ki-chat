"""Chat endpoints."""

from __future__ import annotations

import json
import os

import requests
from flask import Blueprint, Response, jsonify, request, stream_with_context
from pypdf import PdfReader
from werkzeug.utils import secure_filename

from app import current_config

bp = Blueprint("chat", __name__, url_prefix="/api")

DOCUMENT_CHAR_LIMIT = 15_000


def _stream_from_ollama(model: str, messages: list[dict]):
    cfg = current_config()
    try:
        with requests.post(
            f"{cfg.ollama_url}/api/chat",
            json={"model": model, "messages": messages, "stream": True},
            stream=True,
            timeout=(cfg.connect_timeout, cfg.request_timeout),
        ) as response:
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    payload = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                message = payload.get("message") or {}
                if "content" in message:
                    yield message["content"]
    except Exception as exc:
        yield f"\n[Error: {exc}]"


@bp.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    model = data.get("model", "llama3")
    history = data.get("history", [])
    return Response(
        stream_with_context(_stream_from_ollama(model, history)),
        mimetype="text/plain",
    )


@bp.post("/chat-file")
def chat_file():
    """Chat with an attached document."""
    cfg = current_config()
    model = request.form.get("model", "llama3")
    prompt = request.form.get("prompt", "")
    uploaded = request.files.get("file")

    if not uploaded:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        history = json.loads(request.form.get("history", "[]"))
    except json.JSONDecodeError:
        return jsonify({"error": "Malformed history"}), 400

    filename = secure_filename(uploaded.filename or "upload")
    upload_dir = cfg.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filepath = upload_dir / filename

    raw = uploaded.read()
    filepath.write_bytes(raw)

    text_content = ""
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(os.fspath(filepath))
        for page in reader.pages:
            text_content += (page.extract_text() or "") + "\n"
    else:
        text_content = raw.decode("utf-8", errors="ignore")

    history.append(
        {
            "role": "user",
            "content": (
                f"{prompt}\n\n---\nContents of the file '{filename}':\n"
                f"{text_content[:DOCUMENT_CHAR_LIMIT]}"
            ),
        }
    )

    return Response(
        stream_with_context(_stream_from_ollama(model, history)),
        mimetype="text/plain",
    )
