import pytest

from app.main import app


def test_analyze_site_remains_in_openapi():
    assert "post" in app.openapi()["paths"]["/llm/analyze-site"]


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
