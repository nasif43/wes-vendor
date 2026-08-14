from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    resend_api_key: str = ""
    mail_from: str = "onboarding@resend.dev"
    # MD Email (Production/Demo): mahmudtarek1971@gmail.com
    default_cc: str = "muhtasimhossain43@gmail.com"
    secret_key: str = "dev-secret-change-in-production"
    debug: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
