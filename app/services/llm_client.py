"""OpenAI-совместимый LLM-клиент со структурированным JSON-ответом."""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gpt-4o"


class InvalidJSONResponse(Exception):
    """Внутренняя ошибка ответа модели без раскрытия его содержимого."""


class LLMClient:
    """
    Клиент для работы с OpenAI-совместимым LLM API.
    Поддерживает запросы со структурированным JSON-ответом.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ):
        """
        Args:
            base_url: API endpoint. Если None — из env BASE_URL или legacy PROXY_API_URL.
            api_key: Bearer-ключ. Если None — из env OPENAI_API_KEY или legacy API_KEY.
            model: Модель. Если None — из env OPENAI_MODEL или gpt-4o.
            max_tokens: Максимум токенов в ответе (можно менять динамически).
        """
        self._base_url = base_url or os.getenv("BASE_URL") or os.getenv("PROXY_API_URL")
        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY", "")
        self.model = model or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
        self.max_tokens = max_tokens
        self._client = self._create_client()

    def _create_client(self) -> OpenAI:
        """Creates the SDK client without overriding its default endpoint when unset."""
        client_options = {"api_key": self._api_key}
        if self._base_url:
            client_options["base_url"] = self._base_url
        return OpenAI(**client_options)

    @property
    def base_url(self) -> str | None:
        return self._base_url

    @base_url.setter
    def base_url(self, value: str) -> None:
        self._base_url = value
        self._client = self._create_client()

    @property
    def api_key(self) -> str:
        return self._api_key

    @api_key.setter
    def api_key(self, value: str) -> None:
        self._api_key = value
        self._client = self._create_client()

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: str | None = None,
    ) -> dict:
        """
        Запрос со структурированным ответом в формате JSON.
        Ответ парсится в Python-словарь; строгую схему проверяет вызывающий код.

        Args:
            system_prompt: Системный промпт (например, «отвечай только валидным JSON»).
            user_prompt: Текст запроса пользователя.
            json_schema: Описание или схема ожидаемого JSON (добавляется к system_prompt).

        Returns:
            Словарь с распарсенным JSON-ответом.
        """
        full_system = system_prompt
        if json_schema:
            full_system = f"{system_prompt}\n\nОжидаемая структура/схема ответа: {json_schema}"
        messages = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": user_prompt},
        ]
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise InvalidJSONResponse() from exc
