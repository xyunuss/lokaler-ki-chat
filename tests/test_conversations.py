"""Conversation store and its endpoints."""

from __future__ import annotations

from app.storage import Store, derive_title


def test_title_is_derived_from_the_first_line():
    assert derive_title("Explain WAL mode\nand more") == "Explain WAL mode"
    assert derive_title("") == "New chat"
    assert derive_title("x" * 200).endswith("…")


def test_store_round_trip(tmp_path):
    store = Store(tmp_path / "chat.db")
    conversation = store.create_conversation(model="llama3:8b")

    store.add_message(conversation.id, "user", "hello")
    store.add_message(conversation.id, "assistant", "hi", stats={"completionTokens": 3})

    messages = store.list_messages(conversation.id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].stats["completionTokens"] == 3


def test_store_survives_a_restart(tmp_path):
    """The whole point of persisting: a reload must not lose the chat."""
    path = tmp_path / "chat.db"
    conversation = Store(path).create_conversation(title="Keep me")

    reopened = Store(path)
    assert reopened.get_conversation(conversation.id).title == "Keep me"


def test_deleting_a_conversation_removes_its_messages(tmp_path):
    store = Store(tmp_path / "chat.db")
    conversation = store.create_conversation()
    store.add_message(conversation.id, "user", "hello")

    assert store.delete_conversation(conversation.id) is True
    assert store.list_messages(conversation.id) == []


def test_editing_drops_everything_after_that_turn(tmp_path):
    store = Store(tmp_path / "chat.db")
    conversation = store.create_conversation()
    first = store.add_message(conversation.id, "user", "one")
    store.add_message(conversation.id, "assistant", "two")
    store.add_message(conversation.id, "user", "three")

    removed = store.delete_messages_from(conversation.id, first.id)
    assert removed == 3
    assert store.list_messages(conversation.id) == []


def test_search_matches_titles_and_message_bodies(tmp_path):
    store = Store(tmp_path / "chat.db")
    matching = store.create_conversation(title="Databases")
    store.add_message(matching.id, "user", "tell me about postgres")
    store.create_conversation(title="Something else")

    assert [c.id for c in store.list_conversations(query="postgres")] == [matching.id]
    assert [c.id for c in store.list_conversations(query="databas")] == [matching.id]
    assert store.list_conversations(query="nothing here") == []


def test_conversations_are_ordered_by_recent_activity(tmp_path):
    store = Store(tmp_path / "chat.db")
    older = store.create_conversation(title="older")
    newer = store.create_conversation(title="newer")
    store.add_message(older.id, "user", "bump")

    assert next(c.title for c in store.list_conversations()) == "older"
    assert newer.title == "newer"


def test_markdown_export_contains_both_sides(tmp_path):
    store = Store(tmp_path / "chat.db")
    conversation = store.create_conversation(title="Export me", model="llama3:8b")
    store.add_message(conversation.id, "user", "question?")
    store.add_message(conversation.id, "assistant", "answer.")

    markdown = store.export_markdown(conversation.id)
    assert "# Export me" in markdown
    assert "## You" in markdown and "question?" in markdown
    assert "## Assistant" in markdown and "answer." in markdown


def test_crud_endpoints(client):
    created = client.post("/api/conversations", json={"title": "Test"}).get_json()
    assert created["title"] == "Test"

    client.patch(f"/api/conversations/{created['id']}", json={"title": "Renamed"})
    assert client.get(f"/api/conversations/{created['id']}").get_json()["title"] == "Renamed"

    assert client.delete(f"/api/conversations/{created['id']}").status_code == 200
    assert client.get(f"/api/conversations/{created['id']}").status_code == 404


def test_export_endpoint_offers_a_download(client):
    conversation = client.post("/api/conversations", json={"title": "My chat"}).get_json()
    response = client.get(f"/api/conversations/{conversation['id']}/export")

    assert response.status_code == 200
    assert "my-chat.md" in response.headers["Content-Disposition"]
