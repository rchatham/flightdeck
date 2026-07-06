from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings loaded from environment variables and `.env`.

    App-level fields read FLIGHTDECK_-prefixed env vars.
    Integration keys read their natural prefix (AMADEUS_*, KIWI_*, SERPAPI_*).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FLIGHTDECK_",
        extra="ignore",
        populate_by_name=True,
    )

    env: Literal["dev", "test", "prod"] = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8002
    log_level: str = "INFO"

    database_url: str = (
        "postgresql+asyncpg://flightdeck:flightdeck@localhost:5434/flightdeck"
    )
    redis_url: str = "redis://localhost:6382/0"

    amadeus_api_key: str = Field(default="", validation_alias="AMADEUS_API_KEY")
    amadeus_api_secret: str = Field(default="", validation_alias="AMADEUS_API_SECRET")
    amadeus_base_url: str = Field(
        default="https://test.api.amadeus.com",
        validation_alias="AMADEUS_BASE_URL",
    )
    kiwi_api_key: str = Field(default="", validation_alias="KIWI_API_KEY")
    serpapi_api_key: str = Field(default="", validation_alias="SERPAPI_API_KEY")

    # Alert notification channels — both optional; unset means CLI/DB only.
    ntfy_topic: str = ""             # FLIGHTDECK_NTFY_TOPIC, e.g. "reid-flightdeck-a8x2"
    ntfy_server: str = "https://ntfy.sh"
    alert_webhook_url: str = ""      # FLIGHTDECK_ALERT_WEBHOOK_URL, POSTed JSON per alert

    @property
    def api_base_url(self) -> str:
        host = "localhost" if self.api_host in ("0.0.0.0", "") else self.api_host
        return f"http://{host}:{self.api_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
