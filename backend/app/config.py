from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://pricetruth:pricetruth@db:5432/pricetruth"
    frontend_origin: str = "http://localhost:5173"
    request_timeout_seconds: float = 12.0
    max_response_bytes: int = 5_000_000
    max_discovery_candidates: int = 5
    max_sitemap_bytes: int = 5_000_000
    max_sitemap_files: int = 1
    discovery_concurrency: int = 7
    discovery_candidate_concurrency: int = 5
    discovery_search_timeout_seconds: float = 10.0
    discovery_candidate_timeout_seconds: float = 10.0
    discovery_overall_timeout_seconds: float = 45.0
    enforce_robots: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgresql://"):
            return "postgresql+psycopg://" + v[len("postgresql://"):]
        return v


settings = Settings()
