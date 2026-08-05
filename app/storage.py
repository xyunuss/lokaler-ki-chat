"""SQLite persistence for conversations and messages.

The old UI kept the transcript in a JavaScript variable, so a reload threw
the conversation away and there was no way to have more than one. A single
local file is the right amount of machinery for that: no server to run, no
migrations to manage, and the user can delete it to erase everything.

Connections are opened per operation. SQLite handles that fine, and it keeps
the store safe to use from Flask's threaded dev server.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT 'New chat',
    model         TEXT,
    system_prompt TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    stats           TEXT,
    attachments     TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated
    ON conversations(updated_at DESC);
"""

TITLE_MAX_LENGTH = 60


def _now() -> str:
    # Milliseconds, not seconds: conversations are ordered by updated_at, and
    # two updates inside the same second would otherwise sort arbitrarily.
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


@dataclass(frozen=True)
class Message:
    id: int
    role: str
    content: str
    created_at: str
    stats: dict | None = None
    attachments: list | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "createdAt": self.created_at,
            "stats": self.stats,
            "attachments": self.attachments or [],
        }

    def to_chat_turn(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    model: str | None
    system_prompt: str | None
    created_at: str
    updated_at: str
    message_count: int = 0
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "model": self.model,
            "systemPrompt": self.system_prompt,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "messageCount": self.message_count,
            "preview": self.preview,
        }


def derive_title(text: str) -> str:
    """First line of the opening message, shortened - like every chat app."""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return "New chat"
    if len(first_line) <= TITLE_MAX_LENGTH:
        return first_line
    return first_line[: TITLE_MAX_LENGTH - 1].rstrip() + "…"


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- conversations ---------------------------------------------------

    def create_conversation(
        self,
        *,
        title: str = "New chat",
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> Conversation:
        conversation_id = uuid.uuid4().hex
        timestamp = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, model, system_prompt, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, title, model, system_prompt, timestamp, timestamp),
            )
        return Conversation(
            id=conversation_id,
            title=title,
            model=model,
            system_prompt=system_prompt,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def list_conversations(
        self, *, query: str | None = None, limit: int = 200
    ) -> list[Conversation]:
        sql = """
            SELECT c.*,
                   COUNT(m.id) AS message_count,
                   COALESCE((SELECT content FROM messages
                             WHERE conversation_id = c.id AND role = 'user'
                             ORDER BY id LIMIT 1), '') AS preview
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
        """
        params: list[Any] = []
        if query:
            # Local-scale search: a LIKE over titles and message bodies is
            # plenty for a few hundred conversations and needs no FTS build.
            sql += """
            WHERE c.id IN (
                SELECT id FROM conversations WHERE title LIKE ? COLLATE NOCASE
                UNION
                SELECT conversation_id FROM messages WHERE content LIKE ? COLLATE NOCASE
            )
            """
            like = f"%{query}%"
            params += [like, like]

        sql += " GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            Conversation(
                id=row["id"],
                title=row["title"],
                model=row["model"],
                system_prompt=row["system_prompt"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                message_count=row["message_count"],
                preview=(row["preview"] or "")[:160],
            )
            for row in rows
        ]

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if not row:
                return None
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()["n"]

        return Conversation(
            id=row["id"],
            title=row["title"],
            model=row["model"],
            system_prompt=row["system_prompt"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            message_count=count,
        )

    def update_conversation(self, conversation_id: str, **fields: Any) -> Conversation | None:
        allowed = {"title", "model", "system_prompt"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE conversations SET {assignments}, updated_at = ? WHERE id = ?",
                    (*updates.values(), _now(), conversation_id),
                )
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cursor.rowcount > 0

    def touch(self, conversation_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id)
            )

    # -- messages --------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        stats: dict | None = None,
        attachments: list | None = None,
    ) -> Message:
        timestamp = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, stats,"
                " attachments) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    role,
                    content,
                    timestamp,
                    json.dumps(stats) if stats else None,
                    json.dumps(attachments) if attachments else None,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (timestamp, conversation_id)
            )
            message_id = int(cursor.lastrowid or 0)

        return Message(
            id=message_id,
            role=role,
            content=content,
            created_at=timestamp,
            stats=stats,
            attachments=attachments,
        )

    def list_messages(self, conversation_id: str) -> list[Message]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
            ).fetchall()

        return [
            Message(
                id=row["id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
                stats=_loads(row["stats"]),
                attachments=_loads(row["attachments"]),
            )
            for row in rows
        ]

    def update_message(self, message_id: int, content: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE messages SET content = ? WHERE id = ?", (content, message_id)
            )
        return cursor.rowcount > 0

    def delete_messages_from(self, conversation_id: str, message_id: int) -> int:
        """Drop a message and everything after it - used by edit and regenerate."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM messages WHERE conversation_id = ? AND id >= ?",
                (conversation_id, message_id),
            )
        return cursor.rowcount

    def drop_trailing_assistant(self, conversation_id: str) -> bool:
        """Remove the last message if it came from the model (regenerate)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, role FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
            if not row or row["role"] != "assistant":
                return False
            conn.execute("DELETE FROM messages WHERE id = ?", (row["id"],))
        return True

    # -- export ----------------------------------------------------------

    def export_markdown(self, conversation_id: str) -> str | None:
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return None

        lines = [f"# {conversation.title}", ""]
        if conversation.model:
            lines += [f"Model: `{conversation.model}`", ""]
        if conversation.system_prompt:
            lines += ["> **System prompt**", f"> {conversation.system_prompt}", ""]

        for message in self.list_messages(conversation_id):
            who = {"user": "You", "assistant": "Assistant", "system": "System"}[message.role]
            lines.append(f"## {who}")
            if message.attachments:
                names = ", ".join(a.get("name", "?") for a in message.attachments)
                lines.append(f"*Attachments: {names}*")
            lines += ["", message.content, ""]

        return "\n".join(lines)
