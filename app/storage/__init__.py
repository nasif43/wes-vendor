import logging
import os

from app.config import get_settings

logger = logging.getLogger(__name__)

# Kept for backward compatibility — no longer used for filesystem paths.
BUCKET_NAME = ""


def _ensure_upload_dir() -> str:
    """Create the upload directory if it doesn't exist and return its path."""
    settings = get_settings()
    upload_dir = settings.upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


async def close_storage_client() -> None:
    """No-op — filesystem handles its own resources."""
    return None


async def ensure_bucket_exists() -> None:
    """No-op — the upload directory is created on first write."""
    _ensure_upload_dir()


async def upload_file(
    bucket: str,
    path: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str | None:
    """Upload a file to the local filesystem and return its public URL."""
    settings = get_settings()
    upload_dir = settings.upload_dir
    try:
        os.makedirs(upload_dir, exist_ok=True)
        full_path = os.path.join(upload_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data)
        return f"{settings.app_url}/uploads/{path}"
    except Exception as e:
        logger.error("File upload failed [%s]: %s", path, e)
        return None


def get_public_url(bucket: str, path: str) -> str:
    settings = get_settings()
    return f"{settings.app_url}/uploads/{path}"