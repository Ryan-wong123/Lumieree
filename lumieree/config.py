"""Application configuration, driven entirely by environment variables."""

import os


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    # Normalise common URL spellings onto the psycopg 3 driver.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development")  # development | production | testing

    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = _database_url() or "postgresql+psycopg://lumieree:lumieree@localhost:5432/lumieree"
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 1800}

    # Sessions / cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", APP_ENV == "production")
    SESSION_COOKIE_NAME = "lumieree_session"
    PERMANENT_SESSION_LIFETIME = int(os.environ.get("SESSION_LIFETIME_SECONDS", 8 * 3600))

    # Request limits (CSV import is the largest legitimate upload)
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_BYTES", 2 * 1024 * 1024))

    # CSRF
    WTF_CSRF_TIME_LIMIT = None  # token lives as long as the session

    # Rate limiting. Use a shared store (redis://...) when running >1 replica.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", True)
    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "10 per minute;60 per hour")

    # Number of reverse proxies (ingress, load balancer) in front of the app.
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", 0))

    # Passwords
    MIN_PASSWORD_LENGTH = int(os.environ.get("MIN_PASSWORD_LENGTH", 12))

    # Accounts with the admin or super_admin role must have two-factor authentication on (others may opt in).
    REQUIRE_MFA_FOR_ADMINS = _bool("REQUIRE_MFA_FOR_ADMINS", APP_ENV == "production")

    # Receipt header (printed on PDF receipts)
    CLINIC_NAME_ZH = os.environ.get("CLINIC_NAME_ZH", "春秋堂中医药诊所")
    CLINIC_NAME = os.environ.get("CLINIC_NAME", "Harmony TCM Healthcare")
    CLINIC_REG_NO = os.environ.get("CLINIC_REG_NO", "201223383")
    CLINIC_ADDRESS = os.environ.get(
        "CLINIC_ADDRESS", "Blk 412 Bedok North Ave 2 #01-142 Singapore 460412    Tel: 9072 1288"
    )
    FONT_DIR = os.environ.get("FONT_DIR", "")  # optional dir with NotoSansCJKsc-*.otf


class TestingConfig(Config):
    APP_ENV = "testing"
    TESTING = True
    SECRET_KEY = "test-secret-key-not-for-production"  # noqa: S105
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    SESSION_COOKIE_SECURE = False
    RATELIMIT_ENABLED = True
    LOGIN_RATE_LIMIT = "1000 per minute"  # effectively off; the rate-limit test lowers it
    WTF_CSRF_ENABLED = True
    MIN_PASSWORD_LENGTH = 12
    REQUIRE_MFA_FOR_ADMINS = False  # tests that need it switch it on explicitly


def validate(config) -> None:
    """Fail fast on unsafe production settings."""
    if config.get("APP_ENV") == "production":
        secret = config.get("SECRET_KEY") or ""
        if len(secret) < 32 or secret in {"your-secret-key", "change-me"}:  # noqa: S105
            raise RuntimeError("SECRET_KEY must be set to a random value of at least 32 characters in production.")
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError("DATABASE_URL must be set in production.")
    elif not config.get("SECRET_KEY"):
        # Development convenience only; never reachable in production (checked above).
        config["SECRET_KEY"] = "dev-only-insecure-secret-key"  # noqa: S105
