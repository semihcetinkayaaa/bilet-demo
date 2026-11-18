"""Bilet API giriş noktası.

Yerelde çalıştırmak için (backend klasöründe, SSH tüneli açıkken):
    uv run fastapi dev src/bilet_api/main.py
Belgeler ve deneme sayfası: http://127.0.0.1:8000/docs
"""

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from bilet_api import events, orders
from bilet_api.config import settings
from bilet_api.db import get_session

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=f"{settings.brand_name} Bilet API",
    version="0.2.0",
    description="Konser, maç, sinema ve tiyatro biletleri. Ödemeler demo amaçlıdır.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(orders.router)

SessionDep = Annotated[Session, Depends(get_session)]


@app.get("/health", tags=["sistem"])
def health() -> dict[str, str]:
    """API ayakta mı? Veritabanına dokunmaz."""
    return {"status": "ok"}


@app.get("/health/db", tags=["sistem"])
def health_db(session: SessionDep) -> dict[str, str]:
    """Veritabanına bağlanılabiliyor mu?"""
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Veritabanına bağlanılamadı") from exc
    return {"status": "ok", "database": "ok"}
