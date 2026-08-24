from unittest.mock import patch

import pytest

from app.services.llm_client import DEFAULT_MODEL, LLMClient


ENDPOINT_VARIABLES = ("BASE_URL", "PROXY_API_URL")


@pytest.fixture(autouse=True)
def isolated_llm_environment(monkeypatch):
    for variable in (*ENDPOINT_VARIABLES, "OPENAI_API_KEY", "API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")


@patch("app.services.llm_client.OpenAI")
def test_explicit_base_url_takes_precedence(mock_openai, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://canonical.example/v1")
    monkeypatch.setenv("PROXY_API_URL", "https://legacy.example/v1")

    client = LLMClient(base_url="https://explicit.example/v1")

    assert client.base_url == "https://explicit.example/v1"
    mock_openai.assert_called_once_with(
        api_key="test-api-key",
        base_url="https://explicit.example/v1",
    )


@patch("app.services.llm_client.OpenAI")
def test_base_url_environment_variable_takes_precedence(mock_openai, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://canonical.example/v1")
    monkeypatch.setenv("PROXY_API_URL", "https://legacy.example/v1")

    client = LLMClient()

    assert client.base_url == "https://canonical.example/v1"
    mock_openai.assert_called_once_with(
        api_key="test-api-key",
        base_url="https://canonical.example/v1",
    )


@patch("app.services.llm_client.OpenAI")
def test_legacy_proxy_api_url_is_used_when_base_url_is_absent(
    mock_openai,
    monkeypatch,
):
    monkeypatch.setenv("PROXY_API_URL", "https://legacy.example/v1")

    client = LLMClient()

    assert client.base_url == "https://legacy.example/v1"
    mock_openai.assert_called_once_with(
        api_key="test-api-key",
        base_url="https://legacy.example/v1",
    )


@patch("app.services.llm_client.OpenAI")
def test_sdk_default_endpoint_is_used_when_no_endpoint_is_configured(mock_openai):
    client = LLMClient()

    assert client.base_url is None
    assert client.model == DEFAULT_MODEL
    mock_openai.assert_called_once_with(api_key="test-api-key")


@patch("app.services.llm_client.OpenAI")
def test_openai_model_environment_variable_is_used(mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "configured-model")

    client = LLMClient()

    assert client.model == "configured-model"
    mock_openai.assert_called_once_with(api_key="test-api-key")


@patch("app.services.llm_client.OpenAI")
def test_explicit_model_takes_precedence_over_environment(mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "configured-model")

    client = LLMClient(model="explicit-model")

    assert client.model == "explicit-model"
    mock_openai.assert_called_once_with(api_key="test-api-key")
