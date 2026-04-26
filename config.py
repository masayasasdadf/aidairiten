from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")

    crowdworks_email: str = Field("", env="CROWDWORKS_EMAIL")
    crowdworks_password: str = Field("", env="CROWDWORKS_PASSWORD")
    lancers_email: str = Field("", env="LANCERS_EMAIL")
    lancers_password: str = Field("", env="LANCERS_PASSWORD")
    coconala_email: str = Field("", env="COCONALA_EMAIL")
    coconala_password: str = Field("", env="COCONALA_PASSWORD")

    monitor_interval_minutes: int = Field(30, env="MONITOR_INTERVAL_MINUTES")

    min_price_article: int = Field(3000, env="MIN_PRICE_ARTICLE")
    min_price_lp: int = Field(15000, env="MIN_PRICE_LP")
    min_price_translation: int = Field(5000, env="MIN_PRICE_TRANSLATION")
    min_price_default: int = Field(3000, env="MIN_PRICE_DEFAULT")

    dashboard_host: str = Field("0.0.0.0", env="DASHBOARD_HOST")
    dashboard_port: int = Field(8000, env="DASHBOARD_PORT")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
