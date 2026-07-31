from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    
    app_name: str = "Cirquento"
    version: str = "0.4.0"
    environment: str = "development"
    
    # Security
    api_key: str = "change-me-in-production"
    
    # Database
    database_url: str = "sqlite+aiosqlite:///.data/cirquento.db"
    
    # Telemetry
    otlp_endpoint: str = ""

@lru_cache()
def get_settings() -> Settings:
    return Settings()
