#!/usr/bin/env python3
"""A fake Ollama server.

Speaks enough of the Ollama HTTP API to develop and test the whole app
without a GPU, a model download, or Ollama itself:

    python tools/ollama_stub.py --port 11434
    OLLAMA_URL=http://127.0.0.1:11434 python run.py

It streams word by word with realistic pauses and reports the same timing
fields a real server does, so streaming, cancellation and the tokens/s
readout can be verified end to end. The test suite starts it on a random
port; CI therefore needs no model.

Standard library only, on purpose - it must run anywhere.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NS = 1_000_000_000

MODELS = [
    {
        "name": "llama3:8b",
        "model": "llama3:8b",
        "size": 4_661_224_676,
        "modified_at": "2026-01-04T10:00:00Z",
        "details": {
            "family": "llama",
            "parameter_size": "8.0B",
            "quantization_level": "Q4_0",
        },
    },
    {
        "name": "mistral:7b",
        "model": "mistral:7b",
        "size": 4_109_865_159,
        "modified_at": "2026-01-02T09:30:00Z",
        "details": {
            "family": "mistral",
            "parameter_size": "7.2B",
            "quantization_level": "Q4_K_M",
        },
    },
    {
        "name": "qwen2.5-coder:7b",
        "model": "qwen2.5-coder:7b",
        "size": 4_683_073_536,
        "modified_at": "2026-01-08T18:12:00Z",
        "details": {
            "family": "qwen2",
            "parameter_size": "7.6B",
            "quantization_level": "Q4_K_M",
        },
    },
]

REPLY = (
    "Sure. Here is a short answer that streams in like a real model would, "
    "including a fenced code block so the markdown renderer gets exercised:\n\n"
    "```python\n"
    "def greet(name: str) -> str:\n"
    '    return f"Hello, {name}!"\n'
    "```\n\n"
    "And a list, because those render differently:\n\n"
    "- first point\n"
    "- second point\n"
    "- third point\n"
)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    delay = 0.02

    # -- plumbing --------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _begin_stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def _write_chunk(self, payload: dict) -> None:
        """One NDJSON object, chunked so the client sees it immediately."""
        data = (json.dumps(payload) + "\n").encode("utf-8")
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _end_stream(self) -> None:
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:
        if self.path.startswith("/api/tags"):
            self._send_json({"models": MODELS})
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        body = self._read_json()

        if self.path.startswith("/api/chat"):
            self._chat(body)
        elif self.path.startswith("/api/pull"):
            self._pull(body)
        elif self.path.startswith("/api/show"):
            self._show(body)
        else:
            self._send_json({"error": "not found"}, 404)

    def _known(self, name: str) -> bool:
        return any(m["name"] == name for m in MODELS)

    def _show(self, body: dict) -> None:
        name = body.get("name") or ""
        if not self._known(name):
            self._send_json({"error": f"model '{name}' not found"}, 404)
            return
        self._send_json({"details": {"family": "llama"}, "parameters": "stop \"<|end|>\""})

    def _chat(self, body: dict) -> None:
        model = body.get("model") or ""
        if model and not self._known(model):
            self._send_json(
                {"error": f"model '{model}' not found, try pulling it first"}, 404
            )
            return

        # Echo the prompt back so tests can assert what the server forwarded.
        messages = body.get("messages") or []
        last = messages[-1]["content"] if messages else ""
        reply = f"You said: {last[:80]}\n\n{REPLY}" if last else REPLY

        started = time.monotonic()
        self._begin_stream()

        words = reply.split(" ")
        try:
            for index, word in enumerate(words):
                piece = word if index == len(words) - 1 else word + " "
                self._write_chunk(
                    {
                        "model": model,
                        "message": {"role": "assistant", "content": piece},
                        "done": False,
                    }
                )
                time.sleep(self.delay)

            elapsed = time.monotonic() - started
            self._write_chunk(
                {
                    "model": model,
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "total_duration": int(elapsed * NS),
                    "load_duration": int(0.12 * NS),
                    "prompt_eval_count": max(1, len(last.split())),
                    "prompt_eval_duration": int(0.08 * NS),
                    "eval_count": len(words),
                    "eval_duration": int(max(elapsed - 0.2, 0.05) * NS),
                }
            )
            self._end_stream()
        except (BrokenPipeError, ConnectionResetError):
            # The client cancelled - exactly what the stop button should cause.
            pass

    def _pull(self, body: dict) -> None:
        name = body.get("name") or ""
        total = 420_000_000
        self._begin_stream()
        try:
            self._write_chunk({"status": "pulling manifest"})
            time.sleep(self.delay)
            completed = 0
            while completed < total:
                completed = min(total, completed + total // 8)
                self._write_chunk(
                    {
                        "status": f"pulling {name}",
                        "digest": "sha256:stub",
                        "total": total,
                        "completed": completed,
                    }
                )
                time.sleep(self.delay * 3)
            self._write_chunk({"status": "verifying sha256 digest"})
            self._write_chunk({"status": "success"})
            self._end_stream()
        except (BrokenPipeError, ConnectionResetError):
            pass


class StubServer(ThreadingHTTPServer):
    daemon_threads = True
    verbose = False


def serve(port: int = 11434, *, delay: float = 0.02, verbose: bool = False) -> StubServer:
    """Start the stub in a background thread and return the server."""
    Handler.delay = delay
    server = StubServer(("127.0.0.1", port), Handler)
    server.verbose = verbose
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--delay", type=float, default=0.02, help="seconds between tokens")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    server = serve(port=args.port, delay=args.delay, verbose=not args.quiet)
    print(f"Ollama stub listening on http://127.0.0.1:{args.port}")
    print(f"Point the app at it:  OLLAMA_URL=http://127.0.0.1:{args.port} python run.py")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
