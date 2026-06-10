"""
인스타그램 URL + 팔로워 일괄 등록

1단계: CSV로 instagram_url 등록
  python scripts/import_instagram.py --csv instagram_import.csv

2단계: URL이 등록된 인플루언서의 팔로워 자동 조회
  python scripts/import_instagram.py --fetch

CSV 형식 (헤더 필수):
  influencer_id,instagram_url
  mariestoneee,https://www.instagram.com/mariestoneee/
  aliaamustafa8,https://www.instagram.com/aliaamustafa8/

  또는 팔로워를 미리 아는 경우:
  influencer_id,instagram_url,instagram_followers
  mariestoneee,https://www.instagram.com/mariestoneee/,1200000
"""

import os, re, sys, time, csv, argparse
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "supa-apify-pipeline", ".env"))
except ImportError:
    pass

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not all([SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: SUPABASE_URL, SUPABASE_KEY 환경변수를 설정하세요.")
    sys.exit(1)

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "return=minimal",
}
REST = f"{SUPABASE_URL}/rest/v1"


# ─── Instagram 팔로워 조회 (공개 프로필) ──────────────────────────────────────

def _username_from_url(url: str) -> str | None:
    m = re.search(r"instagram\.com/([^/?#]+)", url.rstrip("/"))
    return m.group(1) if m else None


def fetch_instagram_followers(username: str) -> int | None:
    """Instagram 공개 프로필에서 팔로워 수 조회."""
    url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    headers = {
        "User-Agent": "Instagram 76.0.0.15.395 Android (24/7.0; 380dpi; 1080x1920; OnePlus; ONEPLUS A3010; OnePlus3T; qcom; en_US; 138226743)",
        "x-ig-app-id": "936619743392459",
        "Accept-Language": "en-US",
    }
    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code == 200:
            user = r.json().get("data", {}).get("user", {})
            return user.get("edge_followed_by", {}).get("count")
        if r.status_code == 404:
            return None  # 비공개/삭제
    except Exception:
        pass
    return None


# ─── DB 업데이트 ──────────────────────────────────────────────────────────────

def update_instagram(influencer_id: str, instagram_url: str, followers: int | None) -> bool:
    payload = {"instagram_url": instagram_url}
    if followers is not None:
        payload["instagram_followers"] = followers
    try:
        r = requests.patch(
            f"{REST}/influencer_master",
            headers=HEADERS,
            params={"influencer_id": f"eq.{influencer_id}"},
            json=payload,
            timeout=15,
        )
        return r.status_code in (200, 204)
    except Exception:
        return False


# ─── 1단계: CSV 임포트 ────────────────────────────────────────────────────────

def cmd_import_csv(csv_path: str):
    if not os.path.exists(csv_path):
        print(f"ERROR: 파일을 찾을 수 없습니다 — {csv_path}")
        sys.exit(1)

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"=== Instagram URL 등록 ({len(rows)}개) ===\n")
    ok = fail = 0
    for i, row in enumerate(rows, 1):
        iid = row.get("influencer_id", "").strip()
        url = row.get("instagram_url", "").strip()
        followers_raw = row.get("instagram_followers", "").strip()
        followers = int(followers_raw.replace(",", "")) if followers_raw.isdigit() or (followers_raw.replace(",","").isdigit()) else None

        if not iid or not url:
            print(f"  [{i}] 스킵 — influencer_id 또는 instagram_url 누락")
            continue

        if update_instagram(iid, url, followers):
            ok += 1
            status = f"팔로워 {followers:,}" if followers else "URL만 등록"
            print(f"  [{i}/{len(rows)}] @{iid} — {status}")
        else:
            fail += 1
            print(f"  [{i}/{len(rows)}] @{iid} — DB 업데이트 실패")

    print(f"\n완료: 성공 {ok}개 | 실패 {fail}개")
    print("팔로워 조회가 필요하면: python scripts/import_instagram.py --fetch")


# ─── 2단계: 팔로워 자동 조회 ─────────────────────────────────────────────────

def cmd_fetch_followers():
    print("=== Instagram 팔로워 자동 조회 ===\n")

    # instagram_url이 있고 팔로워가 없는 인플루언서 조회
    r = requests.get(
        f"{REST}/influencer_master",
        headers={**HEADERS, "Prefer": ""},
        params={
            "select":             "influencer_id,instagram_url",
            "instagram_url":      "not.is.null",
            "instagram_followers": "is.null",
            "limit":              "5000",
        },
        timeout=30,
    )
    rows = r.json()
    print(f"대상: {len(rows)}명\n")

    if not rows:
        print("팔로워 조회가 필요한 인플루언서가 없습니다.")
        return

    ok = fail = skip = 0
    for i, row in enumerate(rows, 1):
        iid = row["influencer_id"]
        url = row["instagram_url"]
        username = _username_from_url(url)

        if not username:
            skip += 1
            continue

        followers = fetch_instagram_followers(username)
        if followers is None:
            skip += 1
            if i % 20 == 0 or i <= 5:
                print(f"  [{i}/{len(rows)}] @{iid} — 조회 실패 (비공개/삭제)")
        else:
            if update_instagram(iid, url, followers):
                ok += 1
                if i % 20 == 0 or i <= 5:
                    print(f"  [{i}/{len(rows)}] @{iid} — {followers:,}명")
            else:
                fail += 1

        time.sleep(0.5)  # Instagram rate limit

    print(f"\n완료: 성공 {ok}개 | 스킵 {skip}개 | 실패 {fail}개")


# ─── 현황 확인 ────────────────────────────────────────────────────────────────

def cmd_status():
    h = {**HEADERS, "Prefer": "count=exact"}
    total   = requests.get(f"{REST}/influencer_master", headers=h, params={"select":"influencer_id","limit":"1"}).headers.get("content-range","?")
    has_url = requests.get(f"{REST}/influencer_master", headers=h, params={"select":"influencer_id","instagram_url":"not.is.null","limit":"1"}).headers.get("content-range","?")
    has_fol = requests.get(f"{REST}/influencer_master", headers=h, params={"select":"influencer_id","instagram_followers":"not.is.null","limit":"1"}).headers.get("content-range","?")
    print("=== Instagram 데이터 현황 ===")
    print(f"  전체 인플루언서:   {total}")
    print(f"  instagram_url:    {has_url}")
    print(f"  instagram_followers: {has_fol}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--csv",    metavar="FILE", help="CSV로 instagram_url 일괄 등록")
    group.add_argument("--fetch",  action="store_true", help="URL 등록된 인플루언서 팔로워 자동 조회")
    group.add_argument("--status", action="store_true", help="현황 확인")
    args = parser.parse_args()

    if args.csv:
        cmd_import_csv(args.csv)
    elif args.fetch:
        cmd_fetch_followers()
    elif args.status:
        cmd_status()
