from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
CONFIG_DIR = BACKEND_ROOT / "config"

LLMProviderName = Literal["gemini", "sap_ai_core"]
ModelRole = Literal["extraction", "reasoning", "general", "reconciliation"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: LLMProviderName = "gemini"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    data_dir: Path = BACKEND_ROOT / "data"
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "https://nexus-ui.cfapps.eu10-004.hana.ondemand.com"
    )

    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_extraction_model: str = ""
    gemini_reasoning_model: str = ""
    gemini_general_model: str = ""
    gemini_reconciliation_model: str = ""

    xsuaa_url: str = ""
    xsuaa_client_id: str = ""
    xsuaa_client_secret: str = ""
    aicore_api_url: str = ""
    aicore_resource_group: str = "default"
    aicore_openai_api_version: str = "2024-12-01-preview"
    aicore_gpt40_mini_deployment_id: str = ""
    aicore_gpt55_deployment_id: str = ""
    aicore_gpt41_deployment_id: str = ""
    aicore_gpt40_deployment_id: str = ""

    llm_max_retries: int = 3
    llm_retry_base_seconds: float = 0.5
    llm_json_repair_attempts: int = 2
    ai_models_path: Path = CONFIG_DIR / "ai_models.yaml"

    # Kept identical for every provider so the same prompt behaves the same way.
    llm_temperature_cap: float = 0.2
    llm_max_output_tokens: int = 8192
    llm_seed: int = 7
    llm_native_json_schema: bool = True
    # Reasoning models bill hidden thinking tokens to the completion budget, so they
    # need far more room than the visible answer suggests.
    llm_reasoning_max_output_tokens: int = 32768
    # How hard a reasoning model thinks: minimal | low | medium | high.
    # Higher is more accurate and slower; dropped automatically if unsupported.
    llm_reasoning_effort: str = "medium"

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, value: Path | str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        return path

    def gemini_model_for(self, role: ModelRole) -> str:
        # One Gemini model for every role so the prompt contract matches SAP gpt-4.1.
        return self.gemini_model

    def sap_deployment_for(self, role: ModelRole) -> str:
        # One SAP model for every role: gpt-4.1. Other deployment IDs in env are ignored.
        return self.aicore_gpt41_deployment_id

    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
