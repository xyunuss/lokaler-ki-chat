"""Typed client for the Ollama HTTP API.

The previous implementation shelled out to `ollama list` and parsed stdout,
which required the CLI on PATH and could only ever reach a local daemon. Ollama
exposes the same information over HTTP, so this talks to the API instead and
works against a container or a machine on the network.

Everything here is transport only - no Flask, no request context - so it can be
exercised directly from tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import requests

NANOSECONDS_PER_SECOND = 1_000_000_000


class OllamaError(RuntimeError):
    """Ollama could not serve the request.

    `message` is safe to show to a user; `hint` suggests what to do about it.
    """

    def __init__(self, message: str, *, hint: str | None = None, status: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.message, "hint": self.hint}


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_bytes: int = 0
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    modified_at: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ModelInfo:
        details = payload.get("details") or {}
        return cls(
            name=payload.get("name") or payload.get("model") or "unknown",
            size_bytes=int(payload.get("size") or 0),
            family=details.get("family"),
            parameter_size=details.get("parameter_size"),
            quantization=details.get("quantization_level"),
            modified_at=payload.get("modified_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sizeBytes": self.size_bytes,
            "family": self.family,
            "parameterSize": self.parameter_size,
            "quantization": self.quantization,
            "modifiedAt": self.modified_at,
        }


@dataclass(frozen=True)
class ChatStats:
    """Timing Ollama reports with the final chunk of a response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_ms: float = 0.0
    load_ms: float = 0.0
    prompt_ms: float = 0.0
    completion_ms: float = 0.0

    @property
    def tokens_per_second(self) -> float:
        if self.completion_ms <= 0:
            return 0.0
        return round(self.completion_tokens / (self.completion_ms / 1000), 1)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> ChatStats:
        def ms(key: str) -> float:
            return round(int(payload.get(key) or 0) / NANOSECONDS_PER_SECOND * 1000, 1)

        return cls(
            prompt_tokens=int(payload.get("prompt_eval_count") or 0),
            completion_tokens=int(payload.get("eval_count") or 0),
            total_ms=ms("total_duration"),
            load_ms=ms("load_duration"),
            prompt_ms=ms("prompt_eval_duration"),
            completion_ms=ms("eval_duration"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "totalMs": self.total_ms,
            "loadMs": self.load_ms,
            "promptMs": self.prompt_ms,
            "completionMs": self.completion_ms,
            "tokensPerSecond": self.tokens_per_second,
        }


@dataclass(frozen=True)
class TokenEvent:
    """A piece of the assistant's answer."""

    content: str


@dataclass(frozen=True)
class DoneEvent:
    """End of a response, with the timings for that run."""

    stats: ChatStats
    reason: str | None = None


@dataclass(frozen=True)
class PullEvent:
    """Progress while downloading a model."""

    status: str
    completed: int = 0
    total: int = 0
    digest: str | None = None

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return round(self.completed / self.total * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "completed": self.completed,
            "total": self.total,
            "percent": self.percent,
            "digest": self.digest,
        }


ChatEvent = TokenEvent | DoneEvent


@dataclass
class OllamaClient:
    base_url: str = "http://localhost:11434"
    connect_timeout: int = 5
    request_timeout: int = 300
    session: requests.Session = field(default_factory=requests.Session)

    # -- helpers ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    @property
    def _timeout(self) -> tuple[int, int]:
        return (self.connect_timeout, self.request_timeout)

    def _unreachable(self, exc: Exception) -> OllamaError:
        return OllamaError(
            "Cannot reach Ollama.",
            hint=(
                f"Is it running at {self.base_url}? Start it with `ollama serve`, "
                "or set OLLAMA_URL if it listens elsewhere."
            ),
            status=503,
        )

    @staticmethod
    def _error_from_payload(payload: dict[str, Any], status: int) -> OllamaError:
        message = str(payload.get("error") or "Ollama rejected the request.")
        hint = None
        if "not found" in message.lower():
            hint = "Pull the model first, e.g. `ollama pull llama3`."
        return OllamaError(message, hint=hint, status=404 if status == 404 else 502)

    def _stream_ndjson(self, path: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """POST and yield one parsed object per streamed line."""
        try:
            with self.session.post(
                self._url(path), json=payload, stream=True, timeout=self._timeout
            ) as response:
                if response.status_code >= 400:
                    try:
                        body = response.json()
                    except ValueError:
                        body = {"error": response.text[:200]}
                    raise self._error_from_payload(body, response.status_code)

                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        yield json.loads(line.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
        except requests.RequestException as exc:
            raise self._unreachable(exc) from exc

    # -- API -------------------------------------------------------------

    def health(self) -> bool:
        try:
            response = self.session.get(self._url("/api/tags"), timeout=(self.connect_timeout, 10))
            return response.status_code < 500
        except requests.RequestException:
            return False

    def list_models(self) -> list[ModelInfo]:
        try:
            response = self.session.get(self._url("/api/tags"), timeout=(self.connect_timeout, 30))
        except requests.RequestException as exc:
            raise self._unreachable(exc) from exc

        if response.status_code >= 400:
            raise self._error_from_payload({}, response.status_code)

        try:
            payload = response.json()
        except ValueError as exc:
            raise OllamaError("Ollama returned an unreadable model list.") from exc

        models = [ModelInfo.from_api(item) for item in payload.get("models") or []]
        return sorted(models, key=lambda m: m.name)

    def show(self, model: str) -> dict[str, Any]:
        try:
            response = self.session.post(
                self._url("/api/show"), json={"name": model}, timeout=(self.connect_timeout, 30)
            )
        except requests.RequestException as exc:
            raise self._unreachable(exc) from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code >= 400:
            raise self._error_from_payload(payload, response.status_code)
        return payload

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        options: dict[str, Any] | None = None,
        keep_alive: str | None = None,
    ) -> Iterator[ChatEvent]:
        """Stream a chat completion.

        Yields TokenEvent per fragment and a final DoneEvent carrying the
        timings, so the UI can show tokens/s instead of guessing.
        """
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if options:
            payload["options"] = options
        if keep_alive:
            payload["keep_alive"] = keep_alive

        for chunk in self._stream_ndjson("/api/chat", payload):
            if chunk.get("error"):
                raise self._error_from_payload(chunk, 502)

            message = chunk.get("message") or {}
            content = message.get("content")
            if content:
                yield TokenEvent(content)

            if chunk.get("done"):
                yield DoneEvent(ChatStats.from_api(chunk), reason=chunk.get("done_reason"))

    def pull(self, model: str) -> Iterator[PullEvent]:
        """Download a model, yielding progress."""
        for chunk in self._stream_ndjson("/api/pull", {"name": model, "stream": True}):
            if chunk.get("error"):
                raise self._error_from_payload(chunk, 502)
            yield PullEvent(
                status=str(chunk.get("status") or ""),
                completed=int(chunk.get("completed") or 0),
                total=int(chunk.get("total") or 0),
                digest=chunk.get("digest"),
            )
