import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

BUCKET_NAME = "quotation-uploads"


async def ensure_bucket_exists() -> None:
    """Create the storage bucket if it doesn't already exist."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.warning("Supabase credentials not set — skipping bucket creation")
        return

    async with httpx.AsyncClient() as client:
        # Check if bucket exists
        resp = await client.get(
            f"{settings.supabase_url}/storage/v1/bucket",
            headers={
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "apikey": settings.supabase_service_role_key,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            buckets = resp.json()
            names = [b["id"] for b in buckets] if isinstance(buckets, list) else []
            if BUCKET_NAME in names:
                logger.info("Bucket '%s' already exists", BUCKET_NAME)
                return

        # Create the bucket (public, 50MB limit)
        resp = await client.post(
            f"{settings.supabase_url}/storage/v1/bucket",
            headers={
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "apikey": settings.supabase_service_role_key,
                "Content-Type": "application/json",
            },
            json={
                "id": BUCKET_NAME,
                "name": BUCKET_NAME,
                "public": True,
                "file_size_limit": 52428800,  # 50 MB
                "allowed_mime_types": [
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                    "application/pdf",
                ],
            },
            timeout=10,
        )
        if resp.status_code in (200, 201, 409):
            logger.info("Bucket '%s' ready", BUCKET_NAME)
        else:
            logger.error("Failed to create bucket: %s %s", resp.status_code, resp.text)


async def upload_file(
    bucket: str,
    path: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str | None:
    """Upload a file to Supabase Storage and return its public URL."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.error("Supabase credentials not configured — cannot upload")
        return None

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.supabase_url}/storage/v1/object/{bucket}/{path}",
            headers={
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "apikey": settings.supabase_service_role_key,
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            content=data,
            timeout=30,
        )
        if response.status_code in (200, 201):
            return get_public_url(bucket, path)

        logger.error(
            "Upload failed [%s]: %s — %s",
            response.status_code,
            path,
            response.text[:500],
        )
        return None


def get_public_url(bucket: str, path: str) -> str:
    settings = get_settings()
    return f"{settings.supabase_url}/storage/v1/object/public/{bucket}/{path}"
