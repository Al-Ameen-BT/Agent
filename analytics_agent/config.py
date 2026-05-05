import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class AnalyticsSettings(BaseSettings):
    # Defaulting to the same postgres server you're using for pgvector, but a different DB/schema could be specified
    ANALYTICS_POSTGRES_URL: str = os.getenv(
        "ANALYTICS_POSTGRES_URL", 
        "postgresql+psycopg://postgres:postgres@localhost:5432/agent_db"
    )
    
    # External Ticketing API Configuration
    TICKETING_API_URL: str = os.getenv("TICKETING_API_URL", "http://localhost:8000/mock-tickets")
    TICKETING_UPDATE_URL: str = os.getenv("TICKETING_UPDATE_URL", "http://localhost:8000/mock-tickets/update")
    TICKETING_API_KEY: str = os.getenv("TICKETING_API_KEY", "")
    
    # Offline Ollama Configuration
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
    # Limit CPU threads used per Ollama inference call.
    # On an 8-core machine, 4 keeps CPU under ~35-40% during inference.
    # Increase if you want faster responses and have spare CPU headroom.
    OLLAMA_NUM_THREADS: int = int(os.getenv("OLLAMA_NUM_THREADS", "4"))
    
    # Worker Configuration
    # 120s default — gives the server breathing room between Ollama inference cycles.
    # Set POLL_INTERVAL_SECONDS in .env to tune for your server's capacity.
    POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = AnalyticsSettings()
