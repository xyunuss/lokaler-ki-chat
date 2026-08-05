"""Shared fixtures.

Every test runs against the Ollama stub from tools/, so the suite needs no
GPU, no model download and no Ollama installation - it works the same on a
laptop and in CI.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import ollama_stub  # noqa: E402

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def ollama_url() -> str:
    port = _free_port()
    server = ollama_stub.serve(port=port, delay=0)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture
def app(ollama_url, tmp_path):
    return create_app(Config(ollama_url=ollama_url, data_dir=tmp_path / "data"))


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def offline_client(tmp_path):
    """A client pointed at a port with nothing behind it."""
    application = create_app(
        Config(ollama_url="http://127.0.0.1:1", data_dir=tmp_path / "off", connect_timeout=1)
    )
    return application.test_client()


def read_events(response) -> list[dict]:
    """Parse an NDJSON response body into a list of events."""
    return [
        json.loads(line) for line in response.get_data(as_text=True).splitlines() if line.strip()
    ]
