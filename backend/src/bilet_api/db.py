"""Veritabanı bağlantısı."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from bilet_api.config import settings

# pool_pre_ping: kopmuş bağlantıları kullanmadan önce fark eder
# (SSH tüneli kapanıp açıldığında işe yarar).
engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Tüm tablo modelleri bundan türetilir."""


def get_session() -> Iterator[Session]:
    """Her istek için bir veritabanı oturumu açar ve sonunda kapatır."""
    with SessionLocal() as session:
        yield session
