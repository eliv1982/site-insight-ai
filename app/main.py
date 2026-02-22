"""
FastAPI-приложение для работы с LLM.
Запуск: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import llm

app = FastAPI(
    title="LLM API",
    description="API для работы с LLM через Proxy API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(llm.router, prefix="/llm", tags=["llm"])


@app.get("/")
def root():
    """Корневой эндпоинт."""
    return {"message": "LLM API", "docs": "/docs"}
