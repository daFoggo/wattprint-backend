from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_name: str = "Wattprint API"
    version: str = "0.1.0"
    database_url: str = "postgresql+asyncpg://postgres:change-me@localhost:11096/wattprint"
    cors_origins: str = ""

    # Keycloak realm URL exactly as clients see it: it must equal the token's `iss` claim.
    keycloak_issuer: str = "http://localhost:11095/realms/wattprint"
    # Where this process fetches the signing keys; empty = derived from the issuer. In compose the
    # issuer is localhost (what the phone uses) but the API reaches Keycloak as http://keycloak:11095.
    keycloak_jwks_url: str = ""
    # The access token must be minted for this API (audience mapper in the realm).
    keycloak_audience: str = "wattprint-api"
    # Comma separated clients (`azp`) accepted: the mobile app and the web dashboard.
    keycloak_client_ids: str = "wattprint-mobile,wattprint-web"

    # NILM worker (app.modules.nilm.worker): tb_nilm_model.artifact is relative to this directory.
    nilm_model_dir: str = "models/nilm"
    nilm_history_days: int = 90  # how far back a home's first pass starts
    nilm_poll_s: int = 60
    nilm_threads: int = 4  # torch CPU threads, so the API on the same host keeps its share

    @property
    def client_id_list(self) -> list[str]:
        return [c.strip() for c in self.keycloak_client_ids.split(",") if c.strip()]

    @property
    def jwks_url(self) -> str:
        return self.keycloak_jwks_url or f"{self.keycloak_issuer}/protocol/openid-connect/certs"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
