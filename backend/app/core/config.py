from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SYNC_DATABASE_URL: str
    SECRET_KEY: str
    BOT_TOKEN: str = ""
    MANAGER_TG_ID: str = "306983322"
    ADMIN_EMAIL: str = "admin@company.ru"
    ADMIN_PASSWORD: str = "admin123"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24

    class Config:
        env_file = ".env"


settings = Settings()
