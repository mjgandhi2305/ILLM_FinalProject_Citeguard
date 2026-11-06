"""Runtime configuration, loaded from environment variables and an optional `.env` file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ParserStrategy = Literal["hybrid", "llm", "grobid", "heuristic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- identity / politeness -------------------------------------------------------------
    contact_email: str = "citeguard@example.org"
    app_name: str = "CiteGuard"
    app_version: str = "0.1.0"

    # --- verification engine ---------------------------------------------------------------
    max_concurrency: int = Field(default=6, ge=1, le=64)
    http_timeout_s: float = 20.0
    http_max_retries: int = 3
    # DBLP is implemented but off by default: its API currently sits behind an anti-bot
    # challenge that rejects programmatic clients. Add "dblp" here if that changes.
    enabled_sources: list[str] = Field(
        default_factory=lambda: [
            "doi",
            "crossref",
            "openalex",
            "semantic_scholar",
            "arxiv",
            "pubmed",
        ]
    )
    s2_api_key: SecretStr | None = None
    ncbi_api_key: SecretStr | None = None
    openalex_api_key: SecretStr | None = None

    # --- caching ---------------------------------------------------------------------------
    cache_backend: Literal["disk", "memory", "redis", "none"] = "disk"
    cache_dir: Path = Path.home() / ".cache" / "citeguard"
    cache_ttl_hit_s: int = 30 * 24 * 3600
    cache_ttl_miss_s: int = 24 * 3600
    redis_url: str = "redis://localhost:6379/0"

    # --- parsing ---------------------------------------------------------------------------
    parser_strategy: ParserStrategy = "hybrid"
    grobid_url: str | None = None

    # --- LLM (Groq) ------------------------------------------------------------------------
    llm_enabled: bool = True
    groq_api_key: SecretStr | None = None
    llm_model_parse: str = "openai/gpt-oss-20b"
    llm_model_adjudicate: str = "openai/gpt-oss-120b"
    llm_model_reformulate: str = "openai/gpt-oss-20b"
    llm_model_explain: str = "openai/gpt-oss-120b"
    llm_model_suggest: str = "openai/gpt-oss-120b"
    llm_model_claims: str = "openai/gpt-oss-120b"
    llm_fallback_models: list[str] = Field(
        default_factory=lambda: ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    )
    # Published Groq limits for gpt-oss models (per model). Raise these on paid tiers.
    llm_rpm: int = 30
    llm_tpm: int = 8_000
    llm_tpd: int = 200_000
    llm_daily_token_budget: int | None = None
    llm_timeout_s: float = 60.0
    llm_parse_batch_size: int = Field(default=20, ge=1, le=50)

    # --- suggestions -----------------------------------------------------------------------
    suggest_alternatives: bool = True
    default_style: Literal["apa", "ieee", "bibtex"] = "apa"

    # --- service ---------------------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/citeguard.db"
    db_auto_create: bool = True  # create tables on startup (dev); use Alembic in production
    job_backend: Literal["inline", "arq"] = "inline"
    max_concurrent_checks: int = Field(default=2, ge=1)
    shutdown_grace_s: float = 10.0
    max_upload_mb: int = 25
    max_references: int = 500
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    retention_days: int = 30
    auth_enabled: bool = True
    admin_api_key: SecretStr | None = None
    default_rate_limit_per_min: int = 30
    log_level: str = "INFO"
    log_json: bool = False

    @property
    def llm_available(self) -> bool:
        return self.llm_enabled and self.groq_api_key is not None

    @property
    def user_agent(self) -> str:
        return f"{self.app_name}/{self.app_version} (mailto:{self.contact_email})"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
