"""Deployment settings hydrate from the framework database, never the environment."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalyticsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)
    retention_days: int = Field(default=90, ge=1, le=3650)
    """Days of events retained; deletion runs in bounded batches."""
    geo_enabled: bool = True
    """Resolve approximate locations with a locally provisioned GeoLite2 City database."""
    geo_database_path: str = ""
    """Absolute local MMDB path. No database is included in the package."""
    scheduler_enabled: bool = Field(default=True, json_schema_extra={"requires_restart": True})
    """Run periodic retention cleanup in this process."""

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return (init_settings,)
