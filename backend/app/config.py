from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "AI Self-Healing Web Scraper"
    database_url: str = "sqlite:///./data/scraper.db"
    cors_origins: str = "http://localhost:5173"
    request_delay_ms: int = 1000
    page_timeout_ms: int = 45000
    max_html_chars: int = 18000
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    llm_batch_size: int = 8
    llm_detail_batch_size: int = 5
    llm_max_tokens: int = 1500
    llm_max_input_chars: int = 5500
    llm_cache_enabled: bool = True
    extract_detail_pages_default: bool = True
    min_product_confidence: float = 0.55
    supported_product_categories: list[str] = [
        "mobile_phone",
        "smartphone",
        "tablet",
        "laptop",
        "computer",
        "broadband_plan",
        "internet_package",
        "sim_plan",
        "smartwatch",
        "electronics",
        "accessory",
        "book",
        "other_product",
    ]
    auto_apply_threshold: float = 0.90
    review_threshold: float = 0.60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
