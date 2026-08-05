"""Model listing, downloads and health reporting."""

from __future__ import annotations

from conftest import read_events

from app.ollama import ChatStats, ModelInfo


def test_stats_convert_nanoseconds_and_derive_rate():
    stats = ChatStats.from_api(
        {
            "eval_count": 100,
            "eval_duration": 2_000_000_000,  # 2 seconds
            "prompt_eval_count": 12,
            "total_duration": 2_500_000_000,
        }
    )
    assert stats.completion_ms == 2000.0
    assert stats.total_ms == 2500.0
    assert stats.tokens_per_second == 50.0


def test_stats_never_divide_by_zero():
    assert ChatStats.from_api({}).tokens_per_second == 0.0


def test_model_info_reads_the_details_block():
    model = ModelInfo.from_api(
        {
            "name": "llama3:8b",
            "size": 4_661_224_676,
            "details": {"family": "llama", "parameter_size": "8.0B", "quantization_level": "Q4_0"},
        }
    )
    assert model.parameter_size == "8.0B"
    assert model.to_dict()["quantization"] == "Q4_0"


def test_models_endpoint_returns_metadata(client):
    models = client.get("/api/models").get_json()["models"]

    assert [model["name"] for model in models] == ["llama3:8b", "mistral:7b", "qwen2.5-coder:7b"]
    assert models[0]["parameterSize"] == "8.0B"
    assert models[0]["sizeBytes"] > 0


def test_models_endpoint_explains_an_unreachable_ollama(offline_client):
    response = offline_client.get("/api/models")
    assert response.status_code == 503
    assert "OLLAMA_URL" in response.get_json()["hint"]


def test_health_reports_the_dependency(client, offline_client):
    healthy = client.get("/api/health")
    assert healthy.status_code == 200
    assert healthy.get_json()["ollama"]["reachable"] is True

    unhealthy = offline_client.get("/api/health")
    assert unhealthy.status_code == 503
    assert unhealthy.get_json()["ollama"]["reachable"] is False


def test_pull_streams_progress(client):
    response = client.post("/api/models/pull", json={"name": "phi3:mini"})
    events = read_events(response)

    progress = [event for event in events if event["type"] == "progress"]
    assert progress
    assert max(event["percent"] for event in progress) == 100.0
    assert events[-1]["type"] == "done"


def test_pull_requires_a_name(client):
    assert client.post("/api/models/pull", json={}).status_code == 400


def test_show_reports_unknown_models(client):
    assert client.get("/api/models/llama3:8b").status_code == 200
    assert client.get("/api/models/nope:1b").status_code == 404


def test_index_page_is_served(client):
    """The UI is same-origin with the API - no file:// and no CORS wildcard."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Local AI Chat" in response.data
    assert (
        b"Access-Control-Allow-Origin"
        not in response.headers.get("Access-Control-Allow-Origin", "").encode()
    )
