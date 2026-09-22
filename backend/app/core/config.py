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

    # The refresh token doubles as the "session" docs/modules/session_security.md
    # #5 asks for: REFRESH_TOKEN_EXPIRE_DAYS is its absolute timeout, this
    # is its idle timeout -- if a client doesn't call /refresh within this
    # window, the session is dead even though it hasn't hit its absolute
    # expiry yet. Checked/updated inside refresh() itself, which already
    # writes to the database to rotate the token, so this adds no extra
    # query to ordinary API requests.
    SESSION_IDLE_TIMEOUT_MINUTES: int = 60 * 12

    # Login lockout: number of recent failures for a given username, within
    # the window below, before further attempts are rejected outright.
    LOGIN_LOCKOUT_THRESHOLD: int = 5
    LOGIN_LOCKOUT_WINDOW_MINUTES: int = 15

    CORS_ORIGINS: str = ""

    # Domains a generated QR code is allowed to point to when it represents
    # a JDK-controlled resource (docs/modules/common_validation.md #5) --
    # comma-separated, centralized here rather than left to each module.
    ALLOWED_QR_DOMAINS: str = ""

    # Off by default so local HTTP development keeps working with no extra
    # setup. Turn on in production only when this app terminates TLS
    # itself rather than behind a TLS-terminating load balancer/proxy
    # (docs/modules/session_security.md acceptance criterion 14).
    FORCE_HTTPS: bool = False

    # DEBUG is development-only (docs/modules/logging_request_tracing.md
    # #1/#10) -- production sets this to INFO (the default) so verbose
    # diagnostic logging never runs unintentionally in production.
    LOG_LEVEL: str = "INFO"

    # A request slower than this logs at WARN with its duration, so a
    # slow endpoint is greppable without a profiler
    # (docs/modules/logging_request_tracing.md #8/#11).
    SLOW_REQUEST_THRESHOLD_MS: int = 1000

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def allowed_qr_domains(self) -> list[str]:
        return [domain.strip().lower() for domain in self.ALLOWED_QR_DOMAINS.split(",") if domain.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
