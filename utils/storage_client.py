"""Supabase Storage helpers — upload images and return public CDN URLs."""
import os

import requests

_COVERS_BUCKET = "influencer-covers"
_THUMBS_BUCKET = "thumbnails"


def _sb_storage_url() -> str:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    return f"{base}/storage/v1"


def _headers() -> dict:
    key = os.environ.get("SUPABASE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }


def ensure_buckets() -> None:
    """Create public buckets if they don't exist."""
    for bucket in (_COVERS_BUCKET, _THUMBS_BUCKET):
        try:
            requests.post(
                f"{_sb_storage_url()}/bucket",
                headers=_headers(),
                json={"id": bucket, "name": bucket, "public": True},
                timeout=10,
            )
        except Exception:
            pass  # Already exists or non-critical


def upload_image_from_url(
    src_url: str,
    bucket: str,
    path: str,
    apify_token: str = "",
) -> str | None:
    """
    Download image from src_url → upload to Supabase Storage.
    Returns the public URL or None on failure.
    Upserts (overwrites) existing files at the same path.
    """
    try:
        dl_headers: dict = {}
        if apify_token and "api.apify.com" in src_url:
            dl_headers["Authorization"] = f"Bearer {apify_token}"

        resp = requests.get(src_url, headers=dl_headers, timeout=20)
        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        img_bytes = resp.content

        upload_resp = requests.post(
            f"{_sb_storage_url()}/object/{bucket}/{path}",
            headers={
                **_headers(),
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            data=img_bytes,
            timeout=30,
        )
        if upload_resp.status_code not in (200, 201):
            return None

        return get_public_url(bucket, path)
    except Exception as e:
        print(f"  [storage] upload failed {path}: {e}")
        return None


def get_public_url(bucket: str, path: str) -> str:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    return f"{base}/storage/v1/object/public/{bucket}/{path}"


def upload_cover(src_url: str, username: str, apify_token: str = "") -> str | None:
    """Upload influencer cover image. Returns public URL."""
    return upload_image_from_url(src_url, _COVERS_BUCKET, f"{username}.jpg", apify_token)


def upload_thumbnail(src_url: str, username: str, video_id: str, apify_token: str = "") -> str | None:
    """Upload video thumbnail. Returns public URL."""
    return upload_image_from_url(src_url, _THUMBS_BUCKET, f"{username}/{video_id}.jpg", apify_token)
