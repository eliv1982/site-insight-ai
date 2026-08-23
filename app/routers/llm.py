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
