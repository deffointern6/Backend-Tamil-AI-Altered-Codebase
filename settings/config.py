from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyUrl, model_validator

class Settings(BaseSettings):
    # Required variable (boot fails instantly if missing from .env or system env)
    hf_token: str
    database_url: AnyUrl
    redis_url: str = "redis://localhost:6379/0"
    environment: str = "development"
    firebase_project_id: str = "tamil-ai-backend"
    
    # JWT Configuration
    jwt_secret_key: str = "super-secret-tamil-ai-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    cors_origins: str = "*"

    # DB Connection Pool Config
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # RunPod Serverless (optional — only needed when RunPod fallback is enabled)
    runpod_api_key: str = ""

    # Local Model Settings
    use_local_models: bool = False
    local_model_ports: dict = {
        "letter-gen": 7860,
        "paraphrase-gen": 7861,
        "mcq-gen": 7862,
        "tongue-twister": 7863,
        "poem-gen": 7864,
        "email-gen": 7865,
        "proofreader": 7866,
    }
    
    # Automatically read from a local .env configuration file
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        case_sensitive=False
        )

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.environment.lower() == "production":
            if self.jwt_secret_key == "super-secret-tamil-ai-key-change-in-production":
                raise ValueError("JWT_SECRET_KEY must be changed to a secure random value in production!")
        return self

# Create a singleton instance to be used across the app
settings = Settings()