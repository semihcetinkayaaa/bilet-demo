"""Alembic ortamı.

Veritabanı adresi alembic.ini'den değil, uygulamanın kendi ayarlarından
(DATABASE_URL ortam değişkeni ya da backend/.env) okunur.
Böylece şifre hiçbir zaman Git'e yüklenen bir dosyaya yazılmaz.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import bilet_api.models  # noqa: F401  (tabloların metadata'ya kaydı için)
from bilet_api.config import settings
from bilet_api.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Veritabanına bağlanmadan SQL çıktısı üretir (alembic upgrade --sql)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Veritabanına bağlanıp değişiklikleri uygular."""
    connectable = create_engine(
        settings.database_url, poolclass=pool.NullPool, connect_args={"connect_timeout": 10}
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
