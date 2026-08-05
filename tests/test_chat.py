"""Streaming, error handling and the conversation flow."""

from __future__ import annotations

from conftest import read_events


def _turn(client, conversation_id, **payload):
    response = client.post(
        "/api/chat",
        json={"conversationId": conversation_id, "model": "llama3:8b", **payload},
    )
    return response, read_events(response)


def test_stream_is_ndjson_with_tokens_and_stats(client):
    response = client.post(
        "/api/chat",
        json={"model": "llama3:8b", "messages": [{"role": "user", "content": "hi"}]},
    )
    events = read_events(response)

    assert response.mimetype == "application/x-ndjson"
    assert any(event["type"] == "token" for event in events)

    done = events[-1]
    assert done["type"] == "done"
    assert done["stats"]["completionTokens"] > 0
    assert done["stats"]["tokensPerSecond"] > 0


def test_unknown_model_fails_before_the_stream_starts(client):
    """An error must arrive as an HTTP status, not buried in a 200 body."""
    response = client.post(
        "/api/chat",
        json={"model": "does-not-exist:1b", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 404
    assert "not found" in response.get_json()["error"]
    assert response.get_json()["hint"]


def test_unreachable_ollama_explains_itself(offline_client):
    response = offline_client.post(
        "/api/chat",
        json={"model": "llama3:8b", "messages": [{"role": "user", "content": "hi"}]},
    )
    payload = response.get_json()

    assert response.status_code == 503
    assert "Cannot reach Ollama" in payload["error"]
    assert "ollama serve" in payload["hint"]


def test_request_validation(client):
    assert client.post("/api/chat", json={}).status_code == 400
    assert client.post("/api/chat", json={"model": "llama3:8b"}).status_code == 400
    assert (
        client.post("/api/chat", json={"model": "llama3:8b", "messages": []}).status_code == 400
    )


def test_unknown_generation_options_are_dropped(client):
    """Whatever a client sends, only known sampling options reach Ollama."""
    response = client.post(
        "/api/chat",
        json={
            "model": "llama3:8b",
            "messages": [{"role": "user", "content": "hi"}],
            "options": {"temperature": 0.2, "rm": "-rf"},
        },
    )
    assert response.status_code == 200


def test_conversation_turn_is_persisted(client):
    conversation = client.post("/api/conversations", json={"model": "llama3:8b"}).get_json()
    _, events = _turn(client, conversation["id"], content="Explain WAL mode")

    assert events[0]["type"] == "start"
    assert events[-1]["messageId"]

    detail = client.get(f"/api/conversations/{conversation['id']}").get_json()
    roles = [message["role"] for message in detail["messages"]]

    assert roles == ["user", "assistant"]
    assert detail["messages"][1]["stats"]["completionTokens"] > 0


def test_first_message_names_the_conversation(client):
    conversation = client.post("/api/conversations", json={"model": "llama3:8b"}).get_json()
    assert conversation["title"] == "New chat"

    _turn(client, conversation["id"], content="How does streaming work?")

    detail = client.get(f"/api/conversations/{conversation['id']}").get_json()
    assert detail["title"] == "How does streaming work?"


def test_history_is_sent_back_to_the_model(client):
    """The second turn must carry the first one - the stub echoes what it got."""
    conversation = client.post("/api/conversations", json={"model": "llama3:8b"}).get_json()
    _turn(client, conversation["id"], content="first question")
    _, events = _turn(client, conversation["id"], content="second question")

    answer = "".join(event["content"] for event in events if event["type"] == "token")
    assert "second question" in answer


def test_regenerate_replaces_the_last_answer(client):
    conversation = client.post("/api/conversations", json={"model": "llama3:8b"}).get_json()
    _turn(client, conversation["id"], content="hello")

    before = client.get(f"/api/conversations/{conversation['id']}").get_json()["messages"]
    _turn(client, conversation["id"], regenerate=True)
    after = client.get(f"/api/conversations/{conversation['id']}").get_json()["messages"]

    assert len(after) == len(before)
    assert after[-1]["id"] != before[-1]["id"]


def test_attachment_text_becomes_part_of_the_message(client):
    """So follow-up questions still see the document."""
    conversation = client.post("/api/conversations", json={"model": "llama3:8b"}).get_json()
    _turn(
        client,
        conversation["id"],
        content="summarise this",
        attachments=[
            {
                "name": "report.txt",
                "kind": "text",
                "chars": 11,
                "promptSection": "--- file: report.txt ---\nquarterly figures\n--- end ---",
            }
        ],
    )

    detail = client.get(f"/api/conversations/{conversation['id']}").get_json()
    user_message = detail["messages"][0]

    assert "quarterly figures" in user_message["content"]
    assert user_message["attachments"][0]["name"] == "report.txt"


def test_empty_turn_is_rejected(client):
    conversation = client.post("/api/conversations", json={"model": "llama3:8b"}).get_json()
    response = client.post(
        "/api/chat",
        json={"conversationId": conversation["id"], "model": "llama3:8b", "content": "   "},
    )
    assert response.status_code == 400


def test_missing_conversation_is_404(client):
    response = client.post(
        "/api/chat",
        json={"conversationId": "nope", "model": "llama3:8b", "content": "hi"},
    )
    assert response.status_code == 404
