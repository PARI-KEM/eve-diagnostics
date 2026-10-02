from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./eve.db"
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    webhook_secret: str = "dev-only-webhook-secret"
    # Comma separated; users signing up with these emails become admins.
    admin_emails: str = ""
    # Probability the simulated payment provider reports SUCCESS.
    payment_success_rate: float = 0.8
    # Per-IP requests/minute on signup+login. 0 disables.
    rate_limit_per_minute: int = 20
    bcrypt_rounds: int = 12

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
