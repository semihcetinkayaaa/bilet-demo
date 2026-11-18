"""Bilet API giriş noktası.

Yerelde çalıştırmak için (backend klasöründe):
    uv run fastapi dev src/bilet_api/main.py
"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from bilet_api.config import settings
from bilet_api.db import get_session

app = FastAPI(title="Bilet API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

SessionDep = Annotated[Session, Depends(get_session)]


@app.get("/health")
def health() -> dict[str, str]:
    """API ayakta mı? Veritabanına dokunmaz."""
    return {"status": "ok"}


@app.get("/health/db")
def health_db(session: SessionDep) -> dict[str, str]:
    """Veritabanına bağlanılabiliyor mu?"""
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Veritabanına bağlanılamadı") from exc
    return {"status": "ok", "database": "ok"}
