"""Uygulama ayarları.

Değerler ortam değişkenlerinden ya da backend/.env dosyasından okunur.
.env dosyası Git'e yüklenmez; örnek için .env.example dosyasına bakın.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Örnek: postgresql+psycopg://kullanici:sifre@localhost:5433/bilet_dev
    # Coolify'ın verdiği "postgres://..." biçimi de kabul edilir (aşağıda düzeltilir).
    database_url: str

    # Frontend'in API'ye tarayıcıdan erişebileceği adresler (virgülle ayrılmış)
    cors_origins: str = "http://localhost:3000"

    brand_name: str = "semihcetinkaya.tech"
    # E-postadaki bağlantılar için sitenin adresi
    site_url: str = "http://localhost:3000"

    # E-posta (SMTP). smtp_host boşsa e-posta gönderilmez, sadece loglanır.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # ör. "semihcetinkaya.tech <bilet@semihcetinkaya.tech>"
    smtp_starttls: bool = True

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, v: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


settings = Settings()
