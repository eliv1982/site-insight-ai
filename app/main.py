"""FastAPI-приложение для работы с LLM."""

from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


class HealthResponse(BaseModel):
    """Stable response contract for process liveness checks."""

    status: Literal["ok"]


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Report process liveness without touching external dependencies."""
    return HealthResponse(status="ok")


@app.get("/")
def root():
    """Корневой эндпоинт."""
    return {"message": "LLM API", "docs": "/docs"}
