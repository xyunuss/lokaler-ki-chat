"""Runtime configuration, read from the environment once at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OLLAMA_URL = "http://localhost:11434"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """Everything that used to be hard-coded in server.py."""

    ollama_url: str = DEFAULT_OLLAMA_URL
    """Base URL of the Ollama server. Set OLLAMA_URL to point at a remote host
    or a container - the old code shelled out to the local `ollama` binary and
    could only ever talk to localhost."""

    request_timeout: int = 300
    """Seconds to wait for a generation. Generous: a large model on CPU is slow."""

    connect_timeout: int = 5
    """Seconds to wait for the connection itself, so a missing Ollama fails fast."""

    data_dir: Path = Path("data")
    """Uploads and the SQLite database live here."""

    max_upload_bytes: int = 20 * 1024 * 1024

    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            ollama_url=os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/"),
            request_timeout=_env_int("REQUEST_TIMEOUT", 300),
            connect_timeout=_env_int("CONNECT_TIMEOUT", 5),
            data_dir=Path(os.environ.get("DATA_DIR", "data")),
            max_upload_bytes=_env_int("MAX_UPLOAD_MB", 20) * 1024 * 1024,
            host=os.environ.get("HOST", "127.0.0.1"),
            port=_env_int("PORT", 5000),
            debug=os.environ.get("DEBUG", "").lower() in {"1", "true", "yes"},
        )
