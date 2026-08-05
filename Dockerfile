# Local AI Chat
#
# The container runs the web app only. Ollama itself stays on the host, where
# it can reach the GPU - point the app at it with OLLAMA_URL.
#
#   docker build -t local-ai-chat .
#   docker run -p 5000:5000 \
#     -e OLLAMA_URL=http://host.docker.internal:11434 \
#     -v local-ai-chat-data:/data local-ai-chat

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=5000 \
    DATA_DIR=/data \
    OLLAMA_URL=http://host.docker.internal:11434

WORKDIR /app

# Dependencies first so code changes do not invalidate the layer.
COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn

COPY app ./app
COPY static ./static
COPY templates ./templates
COPY tools ./tools
COPY run.py .

# Don't run as root, and let the data volume belong to the app user.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /data /app
USER app

VOLUME ["/data"]
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3).status < 500 else 1)"

# gthread, not the default sync worker: responses are long-lived streams, and
# a single sync worker would block every other request while one generates.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", \
     "--worker-class", "gthread", "--workers", "1", "--threads", "8", \
     "--timeout", "600", \
     "run:app"]
