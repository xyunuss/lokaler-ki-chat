"""Document extraction.

Most of these are regression tests: every case here produced either a crash
or a silently empty document in the previous version.
"""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from app.documents import UnsupportedDocument, extract


def test_plain_text_is_decoded():
    document = extract("notes.md", b"# Title\n\nSome text.")
    assert document.kind == "text"
    assert "Some text." in document.text
    assert document.truncated is False


def test_latin1_text_does_not_become_mojibake():
    # errors="ignore" on utf-8 used to drop these characters entirely.
    document = extract("umlaute.txt", "Grüße aus München".encode("cp1252"))
    assert "Grüße" in document.text


def test_csv_is_aligned_into_columns():
    document = extract("people.csv", b"name,age\nAnna,31\nBob,45\n")
    assert "name | age" in document.text
    assert "Anna | 31" in document.text


def test_json_is_pretty_printed():
    document = extract("config.json", b'{"b":1,"a":[1,2]}')
    assert '"b": 1' in document.text


def test_code_files_are_supported():
    assert extract("main.py", b"def f():\n    return 1\n").kind == "text"


def test_binary_is_rejected():
    with pytest.raises(UnsupportedDocument, match="binary"):
        extract("blob.txt", b"\x00\x01\x02binary")


def test_unknown_extension_is_rejected_with_a_useful_message():
    with pytest.raises(UnsupportedDocument, match="not supported"):
        extract("photo.png", b"\x89PNG fake")


def test_empty_file_is_rejected():
    with pytest.raises(UnsupportedDocument, match="empty"):
        extract("nothing.txt", b"")


def test_truncation_is_reported():
    document = extract("long.txt", b"x" * 5000, char_limit=100)
    assert document.chars == 100
    assert document.truncated is True
    assert "[truncated]" in document.as_prompt_section()


def test_pdf_without_text_layer_is_rejected():
    """A scan used to produce an empty document the model then 'summarised'."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(UnsupportedDocument, match="scan"):
        extract("scan.pdf", buffer.getvalue())


def test_corrupt_pdf_is_rejected():
    with pytest.raises(UnsupportedDocument):
        extract("broken.pdf", b"%PDF-1.4 truncated garbage")


def test_prompt_section_names_the_file():
    section = extract("report.txt", b"content").as_prompt_section()
    assert section.startswith("--- file: report.txt")
    assert "content" in section


def test_upload_endpoint_returns_what_was_read(client):
    response = client.post(
        "/api/documents",
        data={"files": [(io.BytesIO(b"hello"), "a.txt"), (io.BytesIO(b"# H"), "b.md")]},
        content_type="multipart/form-data",
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert [document["name"] for document in payload["documents"]] == ["a.txt", "b.md"]
    assert payload["documents"][0]["chars"] == 5


def test_upload_endpoint_reports_unsupported_files(client):
    response = client.post(
        "/api/documents",
        data={"files": (io.BytesIO(b"\x00\x00"), "x.bin")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 415
    assert "not supported" in response.get_json()["error"]


def test_upload_endpoint_requires_a_file(client):
    response = client.post("/api/documents", data={}, content_type="multipart/form-data")
    assert response.status_code == 400
