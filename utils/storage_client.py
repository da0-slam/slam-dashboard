"""Supabase Storage helpers — upload images and return public CDN URLs."""
import os
import re

import requests

_BUCKET = "tiktok-thumbnails"  # 기존 Supabase Storage 버킷 재사용


def _get_env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        try:
            import streamlit as _st
            val = str(_st.secrets.get(name, ""))
        except Exception:
            pass
    return val.split("\n")[0].strip()


def _sb_storage_url() -> str:
    base = _get_env("SUPABASE_URL").rstrip("/")
    return f"{base}/storage/v1"


def _headers() -> dict:
    key = _get_env("SUPABASE_KEY")
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
        if "cdninstagram.com" in src_url or "fbcdn.net" in src_url:
            dl_headers["Referer"] = "https://www.instagram.com/"

        resp = requests.get(src_url, headers=dl_headers, timeout=20)
        if resp.status_code != 200:
            print(f"  [storage] download failed {resp.status_code}: {src_url[:80]}")
            return None

        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        # HTML이 돌아오면 CDN이 로그인 페이지로 리디렉션한 것 — 업로드 중단
        if "text/html" in content_type or "text/plain" in content_type:
            print(f"  [storage] non-image content_type={content_type}: {src_url[:80]}")
            return None

        img_bytes = resp.content
        if len(img_bytes) < 1000:
            print(f"  [storage] suspiciously small response ({len(img_bytes)}B): {src_url[:80]}")
            return None

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
                print(f"  [storage] upload HTTP {upload_resp.status_code}: {upload_resp.text[:120]}")
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


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")
_NON_IMAGE_EXTS = (".js", ".css", ".json", ".html", ".xml", ".txt", ".svg", ".woff", ".ttf")


def _is_image_url(url: str) -> bool:
    """URL이 이미지 파일인지 확인 (JS·CSS 등 제외)."""
    path = url.lower().split("?")[0].split("#")[0]
    if any(path.endswith(ext) for ext in _NON_IMAGE_EXTS):
        return False
    # CDN URL이면 이미지로 간주 (확장자 없어도)
    if any(d in url for d in ("cdninstagram.com/v/", "fbcdn.net/v/", "scontent-")):
        return True
    # 명시적 이미지 확장자
    return any(path.endswith(ext) for ext in _IMAGE_EXTS)


def _fetch_instagram_thumbnail_embed(post_url: str) -> str | None:
    """Instagram embed 페이지에서 썸네일 추출 (인증 불필요)."""
    try:
        m = re.search(r'/(?:reels?|p|tv)/([^/?#]+)', post_url)
        if not m:
            return None
        shortcode = m.group(1)
        headers = {
            **_request_headers(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        for path in [
            f"/p/{shortcode}/embed/captioned/",
            f"/reel/{shortcode}/embed/captioned/",
            f"/p/{shortcode}/embed/",
        ]:
            try:
                resp = requests.get(
                    f"https://www.instagram.com{path}",
                    headers=headers,
                    timeout=15,
                    allow_redirects=True,
                )
                if resp.status_code != 200:
                    continue
                html = resp.text
                for pat in [
                    r'"display_url"\s*:\s*"([^"]+)"',
                    r'"thumbnail_src"\s*:\s*"([^"]+)"',
                    r'"poster"\s*:\s*"([^"]+)"',
                    # img 태그의 src만 (script src 제외)
                    r'<img[^>]+src="(https://[^"]*(?:cdninstagram\.com|fbcdn\.net)[^"]{20,})"',
                ]:
                    mm = re.search(pat, html)
                    if mm:
                        url = mm.group(1)
                        url = (url.replace('\\u0026', '&')
                                  .replace('\\/', '/')
                                  .replace('\\n', '')
                                  .strip())
                        if url.startswith('http') and _is_image_url(url):
                            return url
                og = _extract_og_image(html)
                if og and _is_image_url(og):
                    return og
            except Exception:
                continue
    except Exception:
        pass
    return None


def _decode_html_entities(s: str) -> str:
    return s.replace('&#38;', '&').replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"')


def _fetch_instagram_thumbnail_imginn(post_url: str) -> str | None:
    """imginn.com 프록시를 통해 Instagram 썸네일 가져오기 (공개 이미지 URL 반환)."""
    try:
        m = re.search(r'/(?:reels?|p|tv)/([^/?#]+)', post_url)
        if not m:
            return None
        shortcode = m.group(1)
        url = f"https://imginn.com/p/{shortcode}/"
        headers = {**_request_headers(), "Referer": "https://imginn.com/"}
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            print(f"  [imginn] HTTP {resp.status_code} for {shortcode}")
            return None
        html = resp.text

        # 1순위: OG 이미지 — 릴 썸네일을 정확히 가리킴 (프로필 사진 아님)
        og = _extract_og_image(html)
        if og:
            og = _decode_html_entities(og)
            if _is_image_url(og) and "t51.2885-19" not in og:  # t51.2885-19 = 프로필 사진(150x150) 제외, t51.2885-15(일반 포스트)는 허용
                return og

        # 2순위: imginn CDN URL 중 릴 썸네일 경로만 (t51.71878-15, t51.82787-15 등)
        # t51.2885-19 = 프로필 사진 → 제외
        for pat in [
            r'<img[^>]+src="(https://s\d+\.imginn\.com/[^"]+)"',
            r'data-src="(https://s\d+\.imginn\.com/[^"]+)"',
        ]:
            for mm in re.finditer(pat, html):
                candidate = _decode_html_entities(mm.group(1))
                if _is_image_url(candidate) and "t51.2885-19" not in candidate:
                    return candidate
    except Exception as e:
        print(f"  [imginn] error: {e}")
    return None


def _fetch_instagram_thumbnail_picuki(post_url: str) -> str | None:
    """picuki.com 프록시를 통해 Instagram 썸네일 추출."""
    try:
        m = re.search(r'/(?:reels?|p|tv)/([^/?#]+)', post_url)
        if not m:
            return None
        shortcode = m.group(1)
        url = f"https://www.picuki.com/media/{shortcode}"
        headers = {**_request_headers(), "Referer": "https://www.picuki.com/"}
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            print(f"  [picuki] HTTP {resp.status_code} for {shortcode}")
            return None
        html = resp.text
        # OG 이미지 우선
        og = _extract_og_image(html)
        if og and _is_image_url(og) and "t51.2885-19" not in og:
            return og
        # 본문 이미지 태그
        mm = re.search(
            r'<img[^>]+class=["\'][^"\']*photo[^"\']*["\'][^>]+src=["\']([^"\']+)["\']',
            html, re.IGNORECASE,
        )
        if mm:
            candidate = mm.group(1)
            if _is_image_url(candidate) and "t51.2885-19" not in candidate:
                return candidate
    except Exception as e:
        print(f"  [picuki] error: {e}")
    return None


def _fetch_instagram_thumbnail_instaloader(post_url: str) -> str | None:
    try:
        import instaloader
        m = re.search(r'/(?:reels?|p|tv)/([^/?#]+)', post_url)
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
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(post_url, download=False)
            if info and info.get("thumbnail"):
                return info["thumbnail"]
    except Exception:
        pass
    return None


def _fetch_instagram_thumbnail(post_url: str) -> str | None:
    # 1순위: imginn.com 프록시
    thumb = _fetch_instagram_thumbnail_imginn(post_url)
    if thumb:
        return thumb
    # 2순위: picuki.com 프록시 (imginn 차단 시 대체)
    thumb = _fetch_instagram_thumbnail_picuki(post_url)
    if thumb:
        return thumb
    # 3순위: embed 페이지
    thumb = _fetch_instagram_thumbnail_embed(post_url)
    if thumb:
        return thumb
    # 4순위: yt-dlp
    thumb = _fetch_instagram_thumbnail_ytdlp(post_url)
    if thumb:
        return thumb
    # 5순위: instaloader
    thumb = _fetch_instagram_thumbnail_instaloader(post_url)
    if thumb:
        return thumb
    # 6순위: OG 태그 직접 파싱
    html = _fetch_html(post_url)
    if html:
        og = _extract_og_image(html)
        if og and _is_image_url(og):
            return og
    return None


def _is_x_profile_url(post_url: str) -> bool:
    """x.com / twitter.com URL이 프로필 페이지인지 확인 (트윗 URL이 아니면 True)."""
    # 트윗 URL 패턴: /status/TWEET_ID 또는 /i/status/TWEET_ID
    return not bool(re.search(r'/(i/)?status/\d+', post_url))


_X_RESERVED = frozenset({
    'home', 'explore', 'search', 'notifications', 'messages',
    'i', 'intent', 'settings', 'compose', 'login', 'logout',
})


def _fetch_x_profile_image(post_url: str) -> str | None:
    """X 프로필 URL에서 unavatar.io를 통해 프로필 이미지 URL 추출."""
    m = re.search(r'(?:twitter\.com|x\.com)/([^/?#&]+)', post_url)
    if not m:
        return None
    username = m.group(1).lstrip('@')
    if username.lower() in _X_RESERVED:
        return None
    try:
        resp = requests.get(
            f'https://unavatar.io/twitter/{username}',
            headers=_request_headers(),
            timeout=12,
            allow_redirects=True,
        )
        if resp.status_code == 200 and 'image' in resp.headers.get('content-type', ''):
            # unavatar.io가 이미지를 직접 서빙 → URL 그대로 반환
            return f'https://unavatar.io/twitter/{username}'
    except Exception as e:
        print(f'  [unavatar] {username}: {e}')
    return None


def _fetch_x_thumbnail(post_url: str) -> str | None:
    """fxtwitter.com / vxtwitter.com 프록시로 X(트위터) 트윗의 미디어 썸네일 추출."""
    if _is_x_profile_url(post_url):
        return None
    # /photo/N 접미사 제거 (프록시에서 OG 이미지 추출용)
    base_url = re.sub(r'/photo/\d+$', '', post_url.rstrip('/'))
    for proxy in ('fxtwitter.com', 'vxtwitter.com'):
        try:
            proxy_url = re.sub(r'https?://(www\.)?(x\.com|twitter\.com)', f'https://{proxy}', base_url)
            resp = requests.get(proxy_url, headers=_request_headers(), timeout=20, allow_redirects=True)
            if resp.status_code != 200:
                print(f"  [{proxy}] HTTP {resp.status_code}")
                continue
            og = _extract_og_image(resp.text)
            if og and _is_image_url(og) and "/profile_images/" not in og:
                return og
        except Exception as e:
            print(f"  [{proxy}] error: {e}")
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
    if platform == "x" or "x.com" in normalized or "twitter.com" in normalized:
        if _is_x_profile_url(normalized):
            return _fetch_x_profile_image(normalized)
        thumb = _fetch_x_thumbnail(normalized)
        if thumb:
            return thumb
        return None  # 트윗 URL이지만 미디어 없으면 OG fallback 스킵
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
    if stored:
        return stored
    # URL 도메인만 체크 (query string에 cdninstagram.com이 포함될 수 있으므로)
    try:
        from urllib.parse import urlparse as _parse
        src_domain = _parse(src_url).netloc
    except Exception:
        src_domain = src_url
    # Instagram 자체 CDN은 쿠키 없이 표시 불가 → fallback 사용 안 함
    _blocked = ("cdninstagram.com", "fbcdn.net", "scontent-")
    if any(d in src_domain for d in _blocked):
        print(f"  [storage] Instagram CDN upload failed, skipping fallback: {src_domain}")
        return None
    # imginn 등 외부 프록시 URL은 fallback으로 저장 (공개 접근 가능)
    return src_url


def _safe_path(value: str, max_len: int = 60) -> str:
    """Storage 경로용 ASCII-safe 문자열로 변환 (한/일/특수문자 → _)."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", (value or "unknown")).strip("_")[:max_len] or "unknown"


def upload_cover(src_url: str, username: str, apify_token: str = "") -> str | None:
    """인플루언서 대표 커버 이미지 업로드. covers/{username}.jpg 경로 사용."""
    return upload_image_from_url(src_url, _BUCKET, f"covers/{_safe_path(username)}.jpg", apify_token)


def upload_thumbnail(src_url: str, username: str, video_id: str, apify_token: str = "") -> str | None:
    """영상 썸네일 업로드. thumbnails/{username}/{video_id}.jpg 경로 사용."""
    return upload_image_from_url(
        src_url, _BUCKET,
        f"thumbnails/{_safe_path(username)}/{_safe_path(video_id)}.jpg",
        apify_token,
    )


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
