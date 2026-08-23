"""
Роутер для эндпоинтов работы с LLM.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.analyzer import AnalyzerError, SiteFetchError, run_site_analysis
from app.services.llm_client import LLMClient

router = APIRouter()
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Возвращает синглтон LLMClient."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


class ChatRequest(BaseModel):
    """Тело запроса для /chat."""

    prompt: str


class ChatWithSystemRequest(BaseModel):
    """Тело запроса для /chat-with-system."""

    system_prompt: str
    user_prompt: str


class ChatJsonRequest(BaseModel):
    """Тело запроса для /chat-json."""

    system_prompt: str
    user_prompt: str
    json_schema: str = ""


class AnalyzeRequest(BaseModel):
    """Тело запроса для /analyze-site."""

    url: str = Field(..., min_length=1, description="URL сайта для анализа")


@router.post("/analyze-site")
def analyze_site(request: AnalyzeRequest) -> dict:
    """
    Анализ сайта по URL: загрузка HTML, очистка текста, пошаговый анализ через LLM,
    итоговый отчёт с кратким содержанием.
    """
    try:
        client = get_llm_client()
        return run_site_analysis(url=request.url, llm_client=client)
    except SiteFetchError as e:
        raise HTTPException(status_code=e.status_code, detail=e.public_message) from e
    except AnalyzerError as e:
        raise HTTPException(status_code=400, detail="Не удалось обработать содержимое сайта") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Не удалось выполнить анализ сайта") from e


@router.post("/chat")
def chat(request: ChatRequest) -> dict:
    """
    Простой чат: один промпт пользователя, ответ текстом.
    Вызывает LLMClient.chat(prompt) -> str.
    """
    try:
        client = get_llm_client()
        reply = client.chat(request.prompt)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat-with-system")
def chat_with_system(request: ChatWithSystemRequest) -> dict:
    """
    Чат с системным промптом.
    Вызывает LLMClient.chat_with_system(system_prompt, user_prompt) -> str.
    """
    try:
        client = get_llm_client()
        reply = client.chat_with_system(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
        )
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat-json")
def chat_json(request: ChatJsonRequest) -> dict:
    """
    Чат с ответом в формате JSON.
    Вызывает LLMClient.chat_json(system_prompt, user_prompt, json_schema) -> dict.
    """
    try:
        client = get_llm_client()
        data = client.chat_json(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            json_schema=request.json_schema or None,
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
