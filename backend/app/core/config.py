from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str
    SECRET_KEY: str
    BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = ""
    MANAGER_TG_ID: str = "306983322"
    # Public HTTPS address opened by Telegram. It must point to the Mini App
    # route on the ERP domain, not directly to the API container.
    MINI_APP_URL: str = "https://erp.oyuns.mn/tg"
    ADMIN_EMAIL: str = "admin@company.ru"
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = "admin123"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    ENTERPRISE_ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30
    # Telegram Mini App sessions use a one-year absolute refresh lifetime.
    TELEGRAM_REFRESH_TOKEN_DAYS: int = 365
    AUTH_COOKIE_SECURE: bool = True
    PUBLIC_APP_URL: str = "https://erp.oyuns.mn"
    CORS_ORIGINS: str = "https://erp.oyuns.mn"
    AUTH_EMAIL_VERIFICATION_ENABLED: bool = False
    PASSWORD_RESET_MINUTES: int = 30
    INVITATION_EXPIRE_HOURS: int = 168
    SMTP_HOST: str = "smtp.resend.com"
    SMTP_PORT: int = 465
    SMTP_USERNAME: str = "resend"
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True
    KNOWLEDGE_UPLOAD_DIR: str = "/app/uploads/knowledge"
    ATTACHMENT_STORAGE_BACKEND: str = "local"
    ATTACHMENT_UPLOAD_DIR: str = "/app/uploads/attachments"
    ATTACHMENT_MAX_BYTES: int = 25 * 1024 * 1024
    AVATAR_UPLOAD_DIR: str = "/app/uploads/avatars"
    AVATAR_MAX_BYTES: int = 2 * 1024 * 1024
    AVATAR_MAX_PIXELS: int = 256
    CLAMAV_ENABLED: bool = False
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = 3310
    CLAMAV_TIMEOUT_SECONDS: float = 10.0
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    GOOGLE_WEBHOOK_URL: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_ASSISTANT_MODEL: str = "gpt-5.6-luna"
    ENTERPRISE_TOOLS_ENABLED: bool = False
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_DIMENSIONS: int = 1536
    ASSISTANT_AUDIT_CONTENT_DAYS: int = 30
    ASSISTANT_AUDIT_METADATA_DAYS: int = 365
    # AI gateway: Redis accelerates exact/circuit cache operations while
    # PostgreSQL/pgvector persists safe semantic cache entries.
    AI_REDIS_URL: str = "redis://redis:6379/0"
    AI_MODEL_REGISTRY_JSON: str = ""
    AI_OPENAI_TIMEOUT_SECONDS: float = 35.0
    AI_EXACT_CACHE_TTL_SECONDS: int = 86_400
    AI_SEMANTIC_CACHE_TTL_SECONDS: int = 86_400
    AI_SEMANTIC_CACHE_THRESHOLD: float = 0.94
    AI_CIRCUIT_FAILURE_THRESHOLD: int = 5
    AI_CIRCUIT_OPEN_SECONDS: int = 30

    class Config:
        env_file = ".env"


settings = Settings()
