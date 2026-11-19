"""grafana uyelik izinleri

Grafana'nın salt okunur kullanıcısı (grafana_ro) users tablosunun sadece kişisel veri
içermeyen sütunlarını okuyabilir: id, kayıt / son giriş / doğrulama zamanları.
E-posta, isim, şifre özeti ve sessions tablosu kapalı kalır.

Revision ID: 8c1d4f2e6a70
Revises: 5b7e2c41a9d3
Create Date: 2026-11-19 10:00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8c1d4f2e6a70'
down_revision: Union[str, Sequence[str], None] = '5b7e2c41a9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
            GRANT SELECT (id, created_at, last_login_at, email_verified_at) ON users TO grafana_ro;
          END IF;
        END
        $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
            REVOKE SELECT (id, created_at, last_login_at, email_verified_at) ON users FROM grafana_ro;
          END IF;
        END
        $$;
    """)
