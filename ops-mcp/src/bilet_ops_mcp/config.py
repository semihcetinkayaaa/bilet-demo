"""Ayarlar: ortam değişkenleri ya da ops-mcp/.env dosyası."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MCP istemcilerinin (ElevenLabs, n8n...) "Authorization: Bearer <token>" ile göndereceği gizli anahtar
    mcp_token: str

    # Salt okunur veritabanı bağlantısı (Grafana'nın grafana_ro kullanıcısı yeterli)
    database_url: str

    # İç ağ adresleri (Coolify 'coolify' ağı). Ulaşılamazsa ilgili araç bunu söyler, çökmez.
    prometheus_url: str = ""
    grafana_url: str = ""
    grafana_token: str = ""  # Grafana'da Viewer rolünde service account token'ı
    backend_url: str = "https://bilet-api.semihcetinkaya.tech"

    # Host başlığı kontrolü (DNS rebinding koruması); virgülle ayrılmış
    allowed_hosts: str = "ops-mcp.semihcetinkaya.tech,localhost:*,127.0.0.1:*"
    port: int = 8000

    @field_validator("database_url")
    @classmethod
    def _plain_postgres(cls, v: str) -> str:
        # psycopg "postgresql://" ister; Coolify "postgres://" verebilir, SQLAlchemy biçimi de gelebilir
        for prefix in ("postgresql+psycopg://", "postgres://"):
            if v.startswith(prefix):
                return "postgresql://" + v[len(prefix):]
        return v

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]


settings = Settings()
