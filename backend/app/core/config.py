from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SQLite by default so the project runs with zero setup; point this at
    # a MySQL URL (mysql+pymysql://...) for staging/production.
    DATABASE_URL: str = "sqlite:///./dev.db"

    # No default on purpose. jdk_clean shipped with a hardcoded fallback
    # ("change-me-in-env") that silently signed every token if .env was
    # ever missing -- see docs/audit/AUTHENTICATION_AUDIT.md #1. Missing
    # this must fail application startup, not fall back to something
    # guessable.
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Login lockout: number of recent failures for a given username, within
    # the window below, before further attempts are rejected outright.
    LOGIN_LOCKOUT_THRESHOLD: int = 5
    LOGIN_LOCKOUT_WINDOW_MINUTES: int = 15

    CORS_ORIGINS: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
