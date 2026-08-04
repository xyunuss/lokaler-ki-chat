"""Document upload and text extraction."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.documents import DEFAULT_CHAR_LIMIT, UnsupportedDocument, extract

bp = Blueprint("documents", __name__, url_prefix="/api")

MAX_FILES_PER_REQUEST = 5


@bp.post("/documents")
def upload_documents():
    """Extract text from one or more uploads.

    Extraction is separate from chatting on purpose: the UI can show what was
    actually read ("12 pages, 8,412 characters") before anything is sent to a
    model, and the extracted text becomes part of the message, so follow-up
    questions still see the document.
    """
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return jsonify({"error": "No file uploaded."}), 400
    if len(files) > MAX_FILES_PER_REQUEST:
        return jsonify({"error": f"At most {MAX_FILES_PER_REQUEST} files at a time."}), 400

    documents = []
    errors = []

    for uploaded in files:
        name = uploaded.filename or "upload"
        try:
            document = extract(name, uploaded.read(), char_limit=DEFAULT_CHAR_LIMIT)
        except UnsupportedDocument as exc:
            errors.append({"name": name, "error": str(exc)})
            continue

        documents.append({**document.to_dict(), "promptSection": document.as_prompt_section()})

    if not documents and errors:
        return jsonify({"error": errors[0]["error"], "errors": errors}), 415

    return jsonify({"documents": documents, "errors": errors})
