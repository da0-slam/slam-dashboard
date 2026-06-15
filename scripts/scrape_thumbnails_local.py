"""
로컬에서 campaign_posts 썸네일 스크랩 후 Supabase 업데이트.

Usage:
    python scripts/scrape_thumbnails_local.py
    python scripts/scrape_thumbnails_local.py --campaign "캠페인이름"
    python scripts/scrape_thumbnails_local.py --platform instagram
    python scripts/scrape_thumbnails_local.py --all   # 기존 썸네일도 덮어쓰기

.env 파일 또는 환경변수에서 SUPABASE_URL, SUPABASE_KEY 읽음.
"""
import os
import sys
import time
import re
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .env 로드
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL, SUPABASE_KEY를 .env 파일에 설정하세요.")
    sys.exit(1)

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}
REST = f"{SUPABASE_URL}/rest/v1"


# ── Supabase 헬퍼 ────────────────────────────────────────────────────────────

def get_campaigns() -> list[dict]:
    r = requests.get(f"{REST}/campaigns", headers=HEADERS,
                     params={"select": "id,name", "order": "name.asc"}, timeout=15)
    r.raise_for_status()
    return r.json()


def get_posts(campaign_id: str | None, platform: str | None, force: bool) -> list[dict]:
    params = {
        "select": "id,brand_id,campaign_id,influencer_name,post_url,platform,thumbnail_url",
        "order": "id.asc",
        "limit": "10000",
    }
    if campaign_id:
        params["campaign_id"] = f"eq.{campaign_id}"
    if platform:
        params["platform"] = f"eq.{platform}"
    if not force:
        # 썸네일 없는 것만 (null인 경우만, 외부 URL 포함 기존 썸네일 있으면 건너뜀)
        params["thumbnail_url"] = "is.null"

    r = requests.get(f"{REST}/campaign_posts", headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def update_thumbnail(post_id: str, brand_id: str, url: str) -> bool:
    r = requests.patch(
        f"{REST}/campaign_posts",
        headers={**HEADERS, "Prefer": "return=minimal"},
        params={"id": f"eq.{post_id}", "brand_id": f"eq.{brand_id}"},
        json={"thumbnail_url": url},
        timeout=15,
    )
    return r.status_code in (200, 204)


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", help="캠페인 이름 (일부만 입력해도 됨)")
    parser.add_argument("--platform", choices=["instagram", "tiktok", "x", "other"])
    parser.add_argument("--all", dest="force", action="store_true",
                        help="이미 썸네일 있어도 재스크랩")
    args = parser.parse_args()

    from utils.storage_client import fetch_and_upload_thumbnail, extract_post_id

    # 캠페인 선택
    campaign_id = None
    campaigns = get_campaigns()
    if args.campaign:
        matched = [c for c in campaigns if args.campaign.lower() in c["name"].lower()]
        if not matched:
            print(f"캠페인을 찾을 수 없습니다: {args.campaign}")
            print("존재하는 캠페인:")
            for c in campaigns:
                print(f"  - {c['name']}")
            sys.exit(1)
        if len(matched) > 1:
            print("여러 캠페인이 매칭됩니다. 더 구체적으로 입력하세요:")
            for c in matched:
                print(f"  - {c['name']}")
            sys.exit(1)
        campaign_id = matched[0]["id"]
        print(f"캠페인: {matched[0]['name']}")
    else:
        # 캠페인 목록 출력 후 선택
        print("\n== 캠페인 목록 ==")
        for i, c in enumerate(campaigns):
            print(f"  {i+1}. {c['name']}")
        print(f"  0. 전체 (모든 캠페인)")
        try:
            sel = int(input("\n번호 선택 (Enter=전체): ") or "0")
        except (ValueError, EOFError):
            sel = 0
        if sel > 0 and sel <= len(campaigns):
            campaign_id = campaigns[sel - 1]["id"]
            print(f"캠페인: {campaigns[sel - 1]['name']}")
        else:
            print("전체 캠페인")

    # 게시물 조회
    print(f"\n게시물 조회 중..." + (f" (플랫폼: {args.platform})" if args.platform else ""))
    posts = get_posts(campaign_id, args.platform, args.force)

    if not posts:
        print("스크랩 대상 게시물이 없습니다.")
        return

    total = len(posts)
    print(f"대상: {total}개\n")

    ok = fail = skip = 0
    t_start = time.time()

    for idx, post in enumerate(posts, 1):
        post_id  = post["id"]
        brand_id = post["brand_id"]
        post_url = post.get("post_url", "")
        platform = post.get("platform", "")
        name     = post.get("influencer_name", "")
        pct      = idx / total * 100

        print(f"[{idx}/{total}] ({pct:.0f}%) [{platform}] {name} — {post_url[:60]}")

        if not post_url:
            print("  → URL 없음, 건너뜀")
            skip += 1
            continue

        storage_key = re.sub(r"[^a-zA-Z0-9_-]+", "_", post_id)[:60]

        try:
            saved = fetch_and_upload_thumbnail(post_url, name or "unknown", storage_key)
        except Exception as e:
            print(f"  → 오류: {e}")
            fail += 1
            continue
        finally:
            # Instagram은 rate limit 방지를 위해 요청 간 딜레이
            if platform == "instagram":
                time.sleep(3)

        if saved:
            ok_ = update_thumbnail(post_id, brand_id, saved)
            if ok_:
                print(f"  ✅ {saved[:80]}")
                ok += 1
            else:
                print(f"  ⚠️  DB 업데이트 실패")
                fail += 1
        else:
            print(f"  ❌ 썸네일 없음")
            fail += 1

    elapsed = int(time.time() - t_start)
    print(f"\n== 완료 ({elapsed}초) ==")
    print(f"  성공: {ok}개  실패: {fail}개  건너뜀: {skip}개")


if __name__ == "__main__":
    main()
