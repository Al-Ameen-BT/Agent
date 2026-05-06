import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class AnalyticsSettings(BaseSettings):
    ANALYTICS_POSTGRES_URL: str = os.getenv(
        "ANALYTICS_POSTGRES_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/agent_db"
    )

    # External Ticketing API
    TICKETING_API_URL: str = os.getenv("TICKETING_API_URL", "http://localhost:8000/mock-tickets")
    TICKETING_UPDATE_URL: str = os.getenv("TICKETING_UPDATE_URL", "http://localhost:8000/mock-tickets/update")
    TICKETING_API_KEY: str = os.getenv("TICKETING_API_KEY", "")
    AGENT_INTEGRATION_KEY: str = os.getenv("AGENT_INTEGRATION_KEY", "")

    # Pagination — adjust these to match your ticketing API's query param names
    # e.g. GET /tickets?page=1&per_page=50
    TICKETING_PAGE_PARAM: str = os.getenv("TICKETING_PAGE_PARAM", "page")
    TICKETING_PER_PAGE_PARAM: str = os.getenv("TICKETING_PER_PAGE_PARAM", "per_page")
    TICKETS_PER_PAGE: int = int(os.getenv("TICKETS_PER_PAGE", "50"))
    # If the ticketing JSON nests tickets under a custom key (e.g. unprocessedTickets), set this env name.
    TICKETING_RESPONSE_LIST_KEY: str = os.getenv("TICKETING_RESPONSE_LIST_KEY", "").strip()

    # Ollama
    # Support both integration vars (OLLAMA_HOST/OLLAMA_MODEL)
    # and root app vars (.env.example uses OLLAMA_URL/MODEL).
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL") or os.getenv("MODEL", "gemma4:e4b")
    # Limit CPU threads used per Ollama inference call.
    # On an 8-core machine, 4 keeps CPU under ~35-40% during inference.
    OLLAMA_NUM_THREADS: int = int(os.getenv("OLLAMA_NUM_THREADS", "4"))

    # Worker timing
    # How long to sleep between tickets during backfill (seconds).
    # Prevents Ollama from being hammered — 2s gap keeps CPU calm.
    BACKFILL_DELAY_SECONDS: float = float(os.getenv("BACKFILL_DELAY_SECONDS", "2.0"))
    # How often to poll for NEW tickets after backfill is complete (seconds).
    POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))

    # Dashboard chat (/api/chat) — tuned for accuracy + responsive streaming
    CHAT_NUM_CTX: int = int(os.getenv("CHAT_NUM_CTX", "8192"))
    CHAT_NUM_PREDICT: int = int(os.getenv("CHAT_NUM_PREDICT", "2048"))
    CHAT_TEMPERATURE: float = float(os.getenv("CHAT_TEMPERATURE", "0.2"))
    CHAT_STREAM_CONNECT_SECONDS: float = float(os.getenv("CHAT_STREAM_CONNECT_SECONDS", "180"))
    CHAT_MAX_STREAM_SECONDS: float = float(os.getenv("CHAT_MAX_STREAM_SECONDS", "600"))
    CHAT_TOKEN_IDLE_SECONDS: float = float(os.getenv("CHAT_TOKEN_IDLE_SECONDS", "180"))
    CHAT_CONTEXT_CACHE_SECONDS: int = int(os.getenv("CHAT_CONTEXT_CACHE_SECONDS", "30"))

    # Fast chat mode (low-latency profile for dashboard chat)
    FAST_CHAT_MODE: bool = os.getenv("FAST_CHAT_MODE", "false").strip().lower() == "true"
    FAST_CHAT_NUM_CTX: int = int(os.getenv("FAST_CHAT_NUM_CTX", "2048"))
    FAST_CHAT_NUM_PREDICT: int = int(os.getenv("FAST_CHAT_NUM_PREDICT", "512"))
    FAST_CHAT_TEMPERATURE: float = float(os.getenv("FAST_CHAT_TEMPERATURE", "0.1"))

    # Prefer .env, but fall back to .env.example for first-run setups.
    # This avoids silently defaulting to localhost/mock endpoints when .env is missing.
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.example"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = AnalyticsSettings()
