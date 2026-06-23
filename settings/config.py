from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyUrl

class Settings(BaseSettings):
    # Required variable (boot fails instantly if missing from .env or system env)
    hf_token: str
    database_url: AnyUrl
    redis_url: str = "redis://localhost:6379/0"
    
    # Automatically read from a local .env configuration file
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        case_sensitive=False
        )

# Create a singleton instance to be used across the app
settings = Settings()