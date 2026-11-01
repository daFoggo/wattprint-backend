from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_name: str = "Wattprint API"
    version: str = "0.1.0"
    database_url: str = "postgresql+asyncpg://postgres:change-me@localhost:5433/wattprint"
    cors_origins: str = ""

    # Required, no default: generate with "openssl rand -hex 32".
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
