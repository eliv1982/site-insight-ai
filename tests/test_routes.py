import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import llm


client = TestClient(app)


def test_health_returns_stable_liveness_response():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_registered_in_openapi():
    schema = app.openapi()

    assert schema["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/HealthResponse"}


def test_health_does_not_enter_analysis_or_llm_paths(monkeypatch):
    def fail_if_called(*args, **kwargs):
        pytest.fail("health check invoked an analysis or LLM path")

    monkeypatch.setattr(llm, "get_llm_client", fail_if_called)
    monkeypatch.setattr(llm, "run_site_analysis", fail_if_called)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_site_remains_in_openapi():
    schema = app.openapi()
    operation = schema["paths"]["/llm/analyze-site"]["post"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalyzeSiteResponse"
    }
    assert schema["components"]["schemas"]["AnalyzeSiteResponse"][
        "additionalProperties"
    ] is False
    assert schema["components"]["schemas"]["SiteContentAnalysis"][
        "additionalProperties"
    ] is False


@pytest.mark.parametrize(
    "path",
    [
        "/llm/chat",
        "/llm/chat-with-system",
        "/llm/chat-json",
    ],
)
def test_generic_chat_endpoint_is_absent_from_openapi(path):
    assert path not in app.openapi()["paths"]
