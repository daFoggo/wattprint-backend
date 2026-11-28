from typing import Literal

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
    # Demo guests (POST /demo/homes/{key}/guest): only the dashboard may ask (its client secret),
    # and the guest is signed in through that client. The service account `wattprint-demo-admin`
    # (manage-users) creates and deletes guest accounts. Either empty = 503.
    wattprint_web_client_secret: str = ""
    demo_admin_client_secret: str = ""

    # NILM worker (app.modules.nilm.worker): tb_nilm_model.artifact is relative to this directory.
    nilm_model_dir: str = "models/nilm"
    # How far a device's NILM estimate is trusted: its energy F1 on the bundle's held-out test.
    nilm_high_f1: float = 0.7
    nilm_medium_f1: float = 0.5
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
    openweather_base_url: str = "https://api.openweathermap.org/data/2.5"
    telegram_api_url: str = "https://api.telegram.org"
    # Where a thumbs-down on Wappi's answer is sent so the maintainers see it at once; empty = off.
    feedback_telegram_token: str = ""
    feedback_telegram_chat: str = ""

    # Copilot: LLM through OpenRouter (OpenAI-compatible); free-form data questions via text2sql.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-6-luna"
    copilot_llm_timeout_s: float = 20.0
    # Chat providers in the order tried (openrouter, astralx): a down one hands over to the next,
    # and is left alone for the cooldown. A provider with no API key is skipped.
    copilot_llm_order: str = "openrouter,astralx"
    copilot_llm_cooldown_s: float = 60.0
    copilot_guard_model: str = "meta-llama/llama-guard-4-12b"  # empty: no content guard
    # How fine the numbers Wappi sends to the model may be, for a home that has not chosen:
    # 'daily' hides hourly views, night minutes and alert hours (spec R3.2).
    copilot_ai_detail_default: Literal["daily", "hourly"] = "daily"
    # Wappi, voice and alert mail need the user's consent (R3.3). Off until the dashboard that asks
    # for it is deployed: dev and prod share this API, and the old dashboard cannot ask.
    # shortcut: nothing is refused while False; set CONSENT_ENFORCED=true when that dashboard ships.
    consent_enforced: bool = False
    text2sql_url: str = "http://host.docker.internal:11101"
    text2sql_connection_id: str = ""
    text2sql_service_key: str = ""
    # Logged in as wattprint_copilot_ro: runs the stored queries of custom watches. Empty = none.
    copilot_database_url: str = ""
    # AstralX (OpenAI-compatible): the chat fallback, speech to text and text to speech.
    astralx_api_key: str = ""
    astralx_base_url: str = "https://token.astralx.com.vn/v1"
    astralx_chat_model: str = "byok/astral-x/claude-haiku-5-5"
    # One model (BAAI bge-m3, 1024-d, Vietnamese and English) at both providers: the same vectors,
    # measured cosine 1.0000, so a question embedded by the fallback still matches stored chunks.
    openrouter_embed_model: str = "baai/bge-m3"
    astralx_embed_model: str = "byok/astral-x/astralx-embed"
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
    def token_url(self) -> str:
        # Next to the JWKS endpoint, so in compose it is reached the same way (http://keycloak:11095).
        return self.jwks_url.removesuffix("/certs") + "/token"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
