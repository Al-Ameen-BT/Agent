import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Backward-compatible env support:
    # - legacy app vars: OLLAMA_URL / MODEL
    # - bridge-specific vars: OLLAMA_HOST / OLLAMA_MODEL
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL") or os.getenv("MODEL") or "gemma4:e4b"
    
    AGENT_BRIDGE_SQLITE_PATH: str = "sqlite:///./agent_bridge.db"
    AGENT_BRIDGE_PERSIST_ANALYSIS: bool = True
    
    AGENT_BRIDGE_REQUIRE_API_KEY: bool = True
    AGENT_BRIDGE_API_KEY: str = "default_dev_key"
    AGENT_BRIDGE_HMAC_SECRET: str = "default_hmac_secret"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
