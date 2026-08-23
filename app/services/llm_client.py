"""
Модуль для общения с LLM через Proxy API (OpenAI-совместимый прокси).
Запросы идут на URL прокси, авторизация — заголовок Authorization: Bearer <api_key>.
Переменные из .env: BASE_URL или PROXY_API_URL, OPENAI_API_KEY или API_KEY.
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gpt-4o"  # или "gpt-3.5-turbo"


class LLMClient:
    """
    Клиент для работы с LLM через Proxy API.
    Поддерживает запросы со структурированным JSON-ответом.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
    ):
        """
        Args:
            base_url: URL Proxy API (не api.openai.com). Если None — из env BASE_URL или PROXY_API_URL.
            api_key: Ключ для прокси (Bearer). Если None — из env OPENAI_API_KEY или API_KEY.
            model: Модель (по умолчанию gpt-4o).
            max_tokens: Максимум токенов в ответе (можно менять динамически).
        """
        self._base_url = base_url or os.getenv("BASE_URL") or os.getenv("PROXY_API_URL", "")
        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY", "")
        self.model = model
        self.max_tokens = max_tokens
        self._client = OpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, value: str) -> None:
        self._base_url = value
        self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)

    @property
    def api_key(self) -> str:
        return self._api_key

    @api_key.setter
    def api_key(self, value: str) -> None:
        self._api_key = value
        self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)

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
        return json.loads(content)
