from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://pricetruth:pricetruth@db:5432/pricetruth"
    frontend_origin: str = "http://localhost:5173"
    request_timeout_seconds: float = 12.0
    max_response_bytes: int = 2_000_000
    max_discovery_candidates: int = 5
    max_sitemap_bytes: int = 4_000_000
    max_sitemap_files: int = 3
    discovery_concurrency: int = 7
    discovery_candidate_concurrency: int = 2
    discovery_search_timeout_seconds: float = 10.0
    discovery_candidate_timeout_seconds: float = 10.0
    discovery_overall_timeout_seconds: float = 35.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
