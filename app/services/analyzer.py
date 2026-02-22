"""
Сервис анализа сайтов: загрузка HTML, очистка текста, пошаговый анализ через LLM.
Загрузка через requests: один таймаут на сокет (включая SSL handshake), стабильно в Docker.
"""

import requests
from bs4 import BeautifulSoup

from app.services.llm_client import LLMClient


class AnalyzerError(Exception):
    """Ошибка анализа: не удалось скачать сайт или распарсить HTML."""

    pass


def normalize_url(url: str) -> str:
    """Добавляет схему https:// если её нет, убирает пробелы."""
    url = (url or "").strip()
    if not url:
        raise AnalyzerError("URL не указан")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def fetch_html(
    url: str,
    connect_timeout: float = 30.0,
    read_timeout: float = 180.0,
) -> str:
    """
    Скачивает HTML по URL через requests.
    timeout=(connect, read): подключение 30 с, чтение ответа до 3 мин (медленные/тяжёлые страницы).
    """
    url = normalize_url(url)
    try:
        r = requests.get(
            url,
            timeout=(connect_timeout, read_timeout),
            allow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        r.raise_for_status()
        return r.text
    except (requests.RequestException, OSError) as e:
        raise AnalyzerError(f"Не удалось скачать сайт: {e!s}") from e


def clean_html_to_text(html: str) -> str:
    """
    Удаляет HTML-теги и возвращает только текст.

    Args:
        html: Исходный HTML.

    Returns:
        Очищенный текст (без тегов).

    Raises:
        AnalyzerError: при ошибке парсинга.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        if not text or not text.strip():
            raise AnalyzerError("После очистки HTML текст пуст")
        return text
    except Exception as e:
        raise AnalyzerError(f"Ошибка парсинга HTML: {e!s}") from e


def _extract_steps_list(data: dict) -> list[str]:
    """Извлекает список шагов из ответа LLM (поддержка полей steps / prompts)."""
    for key in ("steps", "prompts", "шаги", "промпты"):
        if key in data and isinstance(data[key], list):
            return [str(s) for s in data[key]]
    if isinstance(data, list):
        return [str(s) for s in data]
    raise ValueError("В ответе LLM не найден список шагов (ожидаются ключи steps или prompts)")


def run_site_analysis(url: str, llm_client: LLMClient) -> dict:
    """
    Выполняет полный анализ сайта по URL: загрузка, очистка, шаги LLM, финальный отчёт.

    Args:
        url: URL сайта для анализа.
        llm_client: Клиент LLM для запросов.

    Returns:
        Словарь с ключами: url, steps, intermediate_results, final_analysis.
        final_analysis может быть dict (если LLM вернул JSON) или строка.

    Raises:
        AnalyzerError: при ошибке загрузки или парсинга HTML (для HTTP 400).
    """
    url = normalize_url(url)
    html = fetch_html(url)
    cleaned_text = clean_html_to_text(html)

    # 1) Первый запрос: получить список шагов в JSON
    steps_prompt = (
        "Ты бот-анализатор сайтов. Вот текст сайта: [очищенный текст]. "
        "В ответе в формате JSON выдай список из 5-6 шагов (промптов), которые нужно выполнить "
        "для анализа этого сайта и подготовки краткого резюме содержания этого сайта (3-5 предложений)."
    )
    user_with_text = f"Текст сайта:\n\n{cleaned_text[:50000]}"  # ограничение длины
    steps_schema = '{"steps": ["промпт шага 1", "промпт шага 2", ...]}'

    steps_response = llm_client.chat_json(
        system_prompt=steps_prompt,
        user_prompt=user_with_text,
        json_schema=steps_schema,
    )
    steps: list[str] = _extract_steps_list(steps_response)

    # 2) Для каждого шага: системный промпт = шаг, user_prompt = очищенный текст
    intermediate_results: list[str] = []
    for step in steps:
        reply = llm_client.chat_with_system(
            system_prompt=step,
            user_prompt=cleaned_text[:50000],
        )
        intermediate_results.append(reply)

    # 3) Финальный запрос: объединить промежуточные результаты и получить итог
    final_system = (
        "У тебя есть результаты промежуточного анализа: [список ответов]. "
        "Объедини их и выдай итоговый анализ сайта. Ответ должен содержать: краткий анализ, "
        "инструкцию по созданию краткого содержания сайта и три примера вывода такого краткого содержания сайта. "
        "Обязательно включи в анализ оригинальный текст сайта. Ответь в формате JSON."
    )
    intermediate_blob = "\n\n---\n\n".join(
        f"Результат шага {i+1}:\n{r}" for i, r in enumerate(intermediate_results)
    )
    final_user = f"Промежуточные результаты:\n\n{intermediate_blob}\n\nОригинальный текст сайта (фрагмент):\n\n{cleaned_text[:15000]}"
    final_schema = (
        '{"analysis": "краткий анализ сайта", "summary_instruction": "инструкция по созданию краткого содержания", '
        '"example_summaries": ["пример 1", "пример 2", "пример 3"]}'
    )

    final_response = llm_client.chat_json(
        system_prompt=final_system,
        user_prompt=final_user,
        json_schema=final_schema,
    )

    return {
        "url": url,
        "steps": steps,
        "intermediate_results": intermediate_results,
        "final_analysis": final_response,
    }
