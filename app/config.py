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
    # Demo homes a signed-in account can view read-only (app.modules.auth.services.demo).
    demo_homes_file: str = "scripts/demo_homes.toml"

    # NILM worker (app.modules.nilm.worker): tb_nilm_model.artifact is relative to this directory.
    nilm_model_dir: str = "models/nilm"
    nilm_history_days: int = 90  # how far back a home's first pass starts
    nilm_poll_s: int = 60
    nilm_threads: int = 4  # torch CPU threads, so the API on the same host keeps its share

    # Insight worker (app.modules.insight.worker): bills, forecasts, cohorts, alerts, mail.
    insight_poll_s: int = 60
    # Expected-usage model (app.modules.expect): days of history it learns from.
    expect_history_days: int = 365
    # In-context home anomaly: the least excess over the expected band worth an alert (VND).
    anomaly_min_vnd_3h: int = 2000
    anomaly_min_vnd_day: int = 5000
    device_min_vnd: int = 2000  # a device anomaly worth an alert
    # A device forecast's certainty from its holdout's daily error over mean daily kWh (WAPE).
    device_high_wape: float = 0.25
    device_medium_wape: float = 0.5
    device_advice_min_vnd: int = 5000  # advice worth showing, saved by the cycle's end
    # Links in mails point here.
    dashboard_url: str = "http://localhost:11092"
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_from: str = "no-reply@wattprint.local"
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False

    # Weather for the home's province (OpenWeather); empty = /energy/weather answers 503.
    openweather_api_key: str = ""

    # Copilot: LLM through OpenRouter (OpenAI-compatible); free-form data questions via text2sql.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-6-luna"
    copilot_llm_timeout_s: float = 20.0
    copilot_guard_model: str = "meta-llama/llama-guard-4-12b"  # empty: no content guard
    text2sql_url: str = "http://host.docker.internal:11101"
    text2sql_connection_id: str = ""
    text2sql_service_key: str = ""
    # Logged in as wattprint_copilot_ro: runs the stored queries of custom watches. Empty = none.
    copilot_database_url: str = ""
    # Voice: speech to text and text to speech (AstralX, OpenAI-compatible).
    astralx_api_key: str = ""
    astralx_base_url: str = "https://token.astralx.com.vn/v1"
    astralx_stt_model: str = "whisper-large-v3-turbo"
    astralx_tts_model: str = "astralx-tts"
    astralx_tts_voice: str = "speaker_05"

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
