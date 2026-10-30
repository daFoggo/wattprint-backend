from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_name: str = "Wattprint API"
    version: str = "0.1.0"
    database_url: str = "postgresql+asyncpg://postgres:change-me@localhost:5433/wattprint"
    # Better Auth runs as a separate Node service; FastAPI verifies its JWTs with the public JWKS.
    auth_jwks_url: str = "http://localhost:3000/api/auth/jwks"
    # `iss` is the public Better Auth URL (what the phone uses), not the in-network JWKS host.
    auth_issuer: str = "http://localhost:3000"
    auth_audience: str = "wattprint-api"
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
