from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://localsignal:localsignal@localhost:5432/localsignal"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
