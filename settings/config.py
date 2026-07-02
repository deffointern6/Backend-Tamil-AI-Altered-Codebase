from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyUrl

class Settings(BaseSettings):
    # Required variable (boot fails instantly if missing from .env or system env)
    hf_token: str
    database_url: AnyUrl
    redis_url: str = "redis://localhost:6379/0"
    
    # JWT Configuration
    jwt_secret_key: str = "super-secret-tamil-ai-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    cors_origins: str = "*"

    # RunPod Serverless (optional — only needed when RunPod fallback is enabled)
    runpod_api_key: str = ""
    
    # Automatically read from a local .env configuration file
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        case_sensitive=False
        )

# Create a singleton instance to be used across the app
settings = Settings()