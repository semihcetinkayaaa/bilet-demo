"""Veritabanı bağlantısı."""

from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from bilet_api.config import settings

# pool_pre_ping: kopmuş bağlantıları kullanmadan önce fark eder
# (SSH tüneli kapanıp açıldığında işe yarar).
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Veritabanına ulaşılamazsa (ör. SSH tüneli kapalı) dakikalarca beklemek yerine hızlı hata ver.
    connect_args={"connect_timeout": 5},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Tüm tablo modelleri bundan türetilir."""

    # Kısıtlamalara (index, unique, foreign key...) öngörülebilir adlar verir;
    # Alembic migration'larının tutarlı kalması için gerekli.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def get_session() -> Iterator[Session]:
    """Her istek için bir veritabanı oturumu açar ve sonunda kapatır."""
    with SessionLocal() as session:
        yield session
