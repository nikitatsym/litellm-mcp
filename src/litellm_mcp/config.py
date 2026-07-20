"""Centralized configuration via pydantic-settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Empty defaults so import and help generation never require env vars;
    # the client crashes on first use when these are missing.
    litellm_url: str = ""
    litellm_api_key: str = ""


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _reset_settings() -> None:
    """Force re-read from env. Used by tests."""
    global _settings
    _settings = None
