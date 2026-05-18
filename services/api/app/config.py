from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://localsignal:localsignal@localhost:5432/localsignal"
    cors_origins: str = "http://localhost:3000"
    admin_token: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    signal_generate_min_candidate_score: float = 50
    signal_generate_min_evidence_count: int = 2
    signal_generate_min_source_diversity: int = 2

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
