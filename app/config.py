from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Supabase (backup target only — used by nightly dump script, not by app)
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # Database (Local PostgreSQL)
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "wes_vendor"
    db_user: str = "postgres"
    db_password: str = ""

    # PgBouncer (connection pooler, optional — only for multi-worker deployments)
    pgbouncer_host: str = "localhost"
    pgbouncer_port: int = 6432
    pgbouncer_pool_size: int = 10

    # File Uploads (local filesystem)
    upload_dir: str = "/var/wes-vendor/uploads"
    app_url: str = "http://localhost:8000"

    resend_api_key: str = ""
    mail_from: str = "onboarding@resend.dev"
    # MD Email (Production/Demo): mahmudtarek1971@gmail.com
    default_cc: str = "muhtasimhossain43@gmail.com"
    secret_key: str = "dev-secret-change-in-production"
    debug: bool = True
    enable_seed_endpoint: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
