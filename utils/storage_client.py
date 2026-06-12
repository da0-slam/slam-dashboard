"""Supabase Storage helpers — upload images and return public CDN URLs."""
import os
import re

import requests

_BUCKET = "tiktok-thumbnails"  # 기존 Supabase Storage 버킷 재사용


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
    """버킷이 없으면 생성 (이미 있으면 무시)."""
    try:
        requests.post(
            f"{_sb_storage_url()}/bucket",
            headers=_headers(),
            json={"id": _BUCKET, "name": _BUCKET, "public": True},
            timeout=10,
        )
    except Exception:
        pass


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
        dl_headers: dict = {**_request_headers()}
        if apify_token and "api.apify.com" in src_url:
            dl_headers["Authorization"] = f"Bearer {apify_token}"
        if "imginn.com" in src_url:
            dl_headers["Referer"] = "https://imginn.com/"

        resp = requests.get(src_url, headers=dl_headers, timeout=20)
        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        img_bytes = resp.content

        for attempt in range(3):
            try:
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
                if upload_resp.status_code in (200, 201):
                    return get_public_url(bucket, path)
                return None
            except requests.exceptions.ConnectionError:
                if attempt < 2:
                    import time as _t; _t.sleep(2 ** attempt)
                    continue
                raise
    except Exception as e:
        print(f"  [storage] upload failed {path}: {e}")
        return None


def get_public_url(bucket: str, path: str) -> str:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    return f"{base}/storage/v1/object/public/{bucket}/{path}"


def _request_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36",
    }


def _fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_request_headers(), timeout=20)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return None


def _extract_og_image(html: str) -> str | None:
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _fetch_tiktok_thumbnail(post_url: str) -> str | None:
    try:
        resp = requests.get(
            "https://www.tiktok.com/oembed",
            params={"url": post_url},
            headers=_request_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("thumbnail_url"):
                return data["thumbnail_url"]
    except Exception:
        pass

    try:
        resp = requests.post(
            "https://tikwm.com/api/",
            data={"url": post_url, "hd": 0},
            headers=_request_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("cover")
    except Exception:
        pass
    return None


def _fetch_instagram_thumbnail_instaloader(post_url: str) -> str | None:
    try:
        import instaloader
        m = re.search(r'/(?:reel|p|tv)/([^/?#]+)', post_url)
        if not m:
            return None
        shortcode = m.group(1)
        L = instaloader.Instaloader(quiet=True, download_pictures=False,
                                     download_videos=False, download_video_thumbnails=False,
                                     download_geotags=False, download_comments=False,
                                     save_metadata=False)
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        return post.url
    except Exception:
        return None


def _fetch_instagram_thumbnail_ytdlp(post_url: str) -> str | None:
    try:
        import yt_dlp
        for opts_extra in [{"cookiesfrombrowser": ("chrome",)}, {}]:
            try:
                ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, **opts_extra}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(post_url, download=False)
                    if info and info.get("thumbnail"):
                        return info["thumbnail"]
            except Exception:
                continue
    except ImportError:
        pass
    return None


def _fetch_instagram_thumbnail(post_url: str) -> str | None:
    # 1차: instaloader (공개 게시물, 실제 Instagram CDN URL 반환)
    thumb = _fetch_instagram_thumbnail_instaloader(post_url)
    if thumb:
        return thumb
    # 2차: yt-dlp (설치된 경우, 크롬 쿠키 자동 사용)
    thumb = _fetch_instagram_thumbnail_ytdlp(post_url)
    if thumb:
        return thumb
    # 3차: OG 태그 직접 파싱 (로그인 벽으로 거의 실패)
    html = _fetch_html(post_url)
    if html:
        return _extract_og_image(html)
    return None


def fetch_thumbnail_url(post_url: str, platform: str | None = None) -> str | None:
    if not post_url:
        return None
    normalized = post_url.strip()
    if platform:
        platform = platform.lower()
    if platform == "tiktok" or "tiktok.com" in normalized:
        thumb = _fetch_tiktok_thumbnail(normalized)
        if thumb:
            return thumb
    if platform == "instagram" or "instagram.com" in normalized:
        thumb = _fetch_instagram_thumbnail(normalized)
        if thumb:
            return thumb
    html = _fetch_html(normalized)
    if html:
        return _extract_og_image(html)
    return None


def extract_post_id(post_url: str) -> str | None:
    if not post_url:
        return None
    path = post_url.split("?")[0].rstrip("/")
    m = re.search(r"/video/(\d+)", path)
    if m:
        return m.group(1)
    m = re.search(r"/(?:reel|p|tv)/([^/]+)", path)
    if m:
        return m.group(1)
    parts = [p for p in path.split("/") if p]
    return parts[-1] if parts else None


def fetch_and_upload_thumbnail(
    post_url: str,
    username: str,
    post_id: str,
    apify_token: str = "",
) -> str | None:
    src_url = fetch_thumbnail_url(post_url)
    if not src_url:
        return None
    stored = upload_thumbnail(src_url, username, post_id, apify_token)
    return stored or src_url


def upload_cover(src_url: str, username: str, apify_token: str = "") -> str | None:
    """인플루언서 대표 커버 이미지 업로드. covers/{username}.jpg 경로 사용."""
    return upload_image_from_url(src_url, _BUCKET, f"covers/{username}.jpg", apify_token)


def upload_thumbnail(src_url: str, username: str, video_id: str, apify_token: str = "") -> str | None:
    """영상 썸네일 업로드. thumbnails/{username}/{video_id}.jpg 경로 사용."""
    return upload_image_from_url(src_url, _BUCKET, f"thumbnails/{username}/{video_id}.jpg", apify_token)


_STRATEGY_BUCKET = "strategy-files"


def ensure_strategy_bucket() -> None:
    try:
        requests.post(
            f"{_sb_storage_url()}/bucket",
            headers=_headers(),
            json={"id": _STRATEGY_BUCKET, "name": _STRATEGY_BUCKET, "public": True},
            timeout=10,
        )
    except Exception:
        pass


def upload_strategy_file(
    brand_id: str,
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> str | None:
    import uuid as _uuid
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    path = f"{brand_id}/{_uuid.uuid4().hex[:8]}_{safe}"
    ensure_strategy_bucket()
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{_sb_storage_url()}/object/{_STRATEGY_BUCKET}/{path}",
                headers={**_headers(), "Content-Type": content_type, "x-upsert": "true"},
                data=file_bytes,
                timeout=60,
            )
            if resp.status_code in (200, 201):
                return get_public_url(_STRATEGY_BUCKET, path)
            return None
        except requests.exceptions.ConnectionError:
            if attempt < 2:
                import time as _t; _t.sleep(2 ** attempt)
            else:
                raise
    return None
