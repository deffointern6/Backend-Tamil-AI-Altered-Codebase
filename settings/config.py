from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Required variable (boot fails instantly if missing from .env or system env)
    hf_token: str
    
    # defaults
    ocr_endpoint: str = "https://api-inference.huggingface.co/models/mock-ocr"
    voice_endpoint_id: str = "mock-voice-id"
    runpod_key: str = "mock_key"

    # Automatically read from a local .env configuration file
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

# Create a singleton instance to be used across the app
settings = Settings()