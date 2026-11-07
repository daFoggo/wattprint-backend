from datetime import date

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

JWT_ALGORITHM = "HS256"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_name: str = "Wattprint API"
    version: str = "0.1.0"
    database_url: str = "postgresql+asyncpg://postgres:change-me@localhost:5433/wattprint"
    cors_origins: str = ""

    # Required, no default: generate with "openssl rand -hex 32".
    jwt_secret_key: str = Field(min_length=32)
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    # A revoked refresh token replayed within this window is a benign retry, not theft.
    refresh_reuse_grace_seconds: int = 10

    # NILM replay (app/services/simulation.py). Paths are relative to the working directory
    # (/code in the container); docker-compose.nilm.yml mounts the host folders there.
    nilm_repo_path: str = "third_party/NILMFormer"
    nilm_ckpt_dir: str = "checkpoints"
    # = scaler.power_stat2 of the training run (REFIT default: the 10 kW cutoff).
    nilm_scale: float = 10000.0
    # Folder with the REFIT CLEAN_House<N>.csv files.
    refit_csv_dir: str = "/data/CLEAN_REFIT_081116"

    # LLM for the Copilot; empty key = Copilot features off.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = ""
    # Login of the read-only role wattprint_copilot_ro (COPILOT_DB_PASSWORD set before
    # migrating): every query the Copilot builds runs there. Empty = Copilot off.
    copilot_database_url: str = ""
    # Demo only: pin the Copilot's "today" (e.g. 2026-11-05 for the legacy dump, which ends 4 Nov)
    copilot_today: date | None = None

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_model)

    @property
    def copilot_enabled(self) -> bool:
        return bool(self.copilot_database_url) and self.llm_enabled

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
