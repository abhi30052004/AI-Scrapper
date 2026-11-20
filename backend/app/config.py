from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "AI Self-Healing Web Scraper"
    database_url: str = "sqlite:///./data/scraper.db"
    cors_origins: str = "http://localhost:5173"
    request_delay_ms: int = 1000
    page_timeout_ms: int = 45000
    max_html_chars: int = 18000
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    auto_apply_threshold: float = 0.90
    review_threshold: float = 0.60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
