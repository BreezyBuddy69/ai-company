from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=("settings_",))

    # --- Core infra ---
    database_url: str = "postgresql+psycopg://factory:factory@postgres:5432/factory"
    redis_url: str = "redis://redis:6379/0"

    # --- Edge auth ---
    # Shared secret the dashboard sends as X-API-Key. Empty = open (local dev).
    api_key: str = ""
    # Comma-separated IP allowlist, checked in app.core.auth on top of the
    # API key (defense in depth: even a leaked key is useless from an
    # unrecognized IP). Empty = no IP restriction. Behind a reverse proxy
    # (Traefik/Hostinger), set trust_proxy_headers so the real client IP is
    # read from X-Forwarded-For instead of the proxy's own address.
    allowed_ips: str = ""
    trust_proxy_headers: bool = False

    @property
    def allowed_ip_list(self) -> list[str]:
        return [ip.strip() for ip in self.allowed_ips.split(",") if ip.strip()]

    # --- Model router ---
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    model_registry_path: str = "/model_registry.yaml"

    # --- Agent framework ---
    agents_config_dir: str = "/agents/configs"
    agents_prompts_dir: str = "/agents/prompts"
    skills_dir: str = "/skills"

    # --- Scout data sources ---
    github_token: str = ""
    scout_keywords: str = "expensive,manual,tedious,frustrating,workaround,spreadsheet hell,no good tool"

    # --- Context manager ---
    short_term_buffer_max_runs: int = 8
    memory_top_k: int = 5

    # --- Misc ---
    log_level: str = "INFO"
    environment: str = "development"

    @property
    def scout_keyword_list(self) -> list[str]:
        return [k.strip() for k in self.scout_keywords.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def local_repo_paths(settings: Settings) -> tuple[Path, Path, Path]:
    """Fallback paths for running outside Docker (dev_dry_run.py) where the
    absolute /agents, /skills, /model_registry.yaml mounts don't exist."""
    root = Path(__file__).resolve().parents[2]  # ai-company/
    return root / "agents" / "configs", root / "agents" / "prompts", root / "skills"
