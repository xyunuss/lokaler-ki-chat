"""Development entry point: `python run.py`."""

from __future__ import annotations

from app import create_app
from app.config import Config

config = Config.from_env()
app = create_app(config)

if __name__ == "__main__":
    print(f"Local AI Chat -> http://{config.host}:{config.port}")
    print(f"Ollama        -> {config.ollama_url}")
    app.run(host=config.host, port=config.port, debug=config.debug, threaded=True)
