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
    Поддерживает обычные запросы, запросы с системным промптом и структурированный JSON-ответ.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        system_prompt: str | None = None,
        max_tokens: int = 4096,
    ):
        """
        Args:
            base_url: URL Proxy API (не api.openai.com). Если None — из env BASE_URL или PROXY_API_URL.
            api_key: Ключ для прокси (Bearer). Если None — из env OPENAI_API_KEY или API_KEY.
            model: Модель (по умолчанию gpt-4o).
            system_prompt: Системный промпт по умолчанию (можно менять динамически).
            max_tokens: Максимум токенов в ответе (можно менять динамически).
        """
        self._base_url = base_url or os.getenv("BASE_URL") or os.getenv("PROXY_API_URL", "")
        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY", "")
        self.model = model
        self.system_prompt = system_prompt
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

    def chat(self, prompt: str) -> str:
        """
        Простой запрос к модели. Возвращает текст ответа.

        Args:
            prompt: Текст запроса пользователя.

        Returns:
            Текст ответа модели.
        """
        messages = [{"role": "user", "content": prompt}]
        if self.system_prompt:
            messages.insert(0, {"role": "system", "content": self.system_prompt})
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    def chat_with_system(self, system_prompt: str, user_prompt: str) -> str:
        """
        Запрос с явным системным промптом.

        Args:
            system_prompt: Системный промпт (роль модели).
            user_prompt: Текст запроса пользователя.

        Returns:
            Текст ответа модели.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        """
        Запрос со структурированным ответом в формате JSON.
        Ответ парсится в Python-словарь.

        Args:
            system_prompt: Системный промпт (например, «отвечай только валидным JSON»).
            user_prompt: Текст запроса пользователя.

        Returns:
            Словарь с распарсенным JSON-ответом.
        """
        messages = [
            {"role": "system", "content": system_prompt},
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


if __name__ == "__main__":
    # Подключение через Proxy API: URL прокси + ключ (Bearer)
    base_url = os.getenv("BASE_URL") or os.getenv("PROXY_API_URL")
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")

    if not base_url or not api_key:
        print("Для тестов задайте в .env: BASE_URL (или PROXY_API_URL) и OPENAI_API_KEY (или API_KEY)")
        exit(1)

    client = LLMClient(base_url=base_url, api_key=api_key, model="gpt-4o", max_tokens=256)

    print("--- 1. chat(prompt) ---")
    try:
        reply = client.chat("Скажи одним предложением: что такое API?")
        print(f"Ответ: {reply}")
    except Exception as e:
        print(f"Ошибка: {e}")

    print("\n--- 2. chat_with_system(system_prompt, user_prompt) ---")
    try:
        reply = client.chat_with_system(
            system_prompt="Ты помощник. Отвечай кратко и по-русски.",
            user_prompt="Назови столицу Франции.",
        )
        print(f"Ответ: {reply}")
    except Exception as e:
        print(f"Ошибка: {e}")

    print("\n--- 3. chat_json(system_prompt, user_prompt) ---")
    try:
        data = client.chat_json(
            system_prompt="Отвечай только валидным JSON без markdown. Формат: {\"answer\": \"твой ответ\"}",
            user_prompt="Столица России — один город. Верни его в поле answer.",
        )
        print(f"Словарь: {data}")
    except Exception as e:
        print(f"Ошибка: {e}")
