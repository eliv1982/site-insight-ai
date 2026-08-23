import pytest

from app.main import app


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
