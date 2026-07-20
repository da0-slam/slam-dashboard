"""
Google Sheet 데이터를 로컬에서 직접 Supabase로 이관.
Railway 타임아웃 없이 안정적으로 동작.

Usage:
    python scripts/migrate_local.py --sheet "구글시트URL" --campaign "캠페인이름"
    python scripts/migrate_local.py --sheet "구글시트URL" --campaign "캠페인이름" --overwrite
    python scripts/migrate_local.py --sheet "구글시트URL" --campaign "캠페인이름" --overwrite --participants 261
"""
import os
import sys
import re
import argparse
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
import pandas as pd

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

_HEADER_NAMES = {
    "name", "full name", "인플루언서", "인플루언서명", "influencer",
    "influencer_name", "이름", "계정", "아이디", "id",
}

COL_ALIASES = {
    "name":           ["name", "full name", "인플루언서", "influencer", "influencer_name"],
    "ig_url":         ["ig_url", "posting url (ig)", "ig url", "instagram_url", "instagram url"],
    "tt_url":         ["tt_url", "posting url (tt)", "tt url", "tiktok_url", "tiktok url"],
    "x_url":          ["x_url", "posting url (x)", "x url", "twitter_url", "x/twitter url"],
    "lips_url":       ["lips_url", "others(lips)", "others(lip)", "lips url", "lips posting url", "other url"],
    "upload_day":     ["upload_day", "upload day", "uploadday", "날짜", "date", "visit date"],
    "tt_views":       ["tt_views", "views", "view", "조회수", "재생수"],
    "tt_likes":       ["tt_likes", "likes", "likes▼", "likes♥", "like", "좋아요"],
    "tt_comments":    ["tt_comments", "comments", "comment", "댓글"],
    "tt_saves":       ["tt_saves", "saves", "save", "저장"],
    "tt_shares":      ["tt_shares", "shares", "share", "공유"],
    "ig_views":       ["ig_views", "views(ig)", "views_ig"],
    "ig_likes":       ["ig_likes", "likes(ig)", "likes▼(ig)", "likes♥(ig)", "likes_ig"],
    "ig_comments":    ["ig_comments", "comments(ig)", "comments_ig"],
    "ig_saves":       ["ig_saves", "saves(ig)", "saves_ig"],
    "ig_shares":      ["ig_shares", "shares(ig)", "shares_ig"],
    "x_views":        ["x_views", "views(x)", "views_x"],
    "x_likes":        ["x_likes", "likes(x)", "likes_x"],
    "x_comments":     ["x_comments", "comments(x)", "comments_x"],
    "x_saves":        ["x_saves", "saves(x)", "saves_x"],
    "x_shares":       ["x_shares", "shares(x)", "shares_x"],
    "other_views":    ["other_views", "lips_views", "views(lips)", "views(other)"],
    "other_likes":    ["other_likes", "lips_likes", "likes(lips)", "likes(other)"],
    "other_comments": ["other_comments", "lips_comments", "comments(lips)"],
    "other_saves":    ["other_saves", "lips_saves", "saves(lips)"],
    "other_shares":   ["other_shares", "lips_shares", "shares(lips)"],
}


# ── Supabase REST 헬퍼 ────────────────────────────────────────────────────────

def get_campaigns() -> list[dict]:
    r = requests.get(f"{REST}/campaigns", headers=HEADERS,
                     params={"select": "id,name,brand_id", "order": "name.asc"}, timeout=15)
    r.raise_for_status()
    return r.json()


def find_post_by_url(post_url: str) -> dict | None:
    r = requests.get(f"{REST}/campaign_posts", headers=HEADERS,
                     params={"select": "id,brand_id", "post_url": f"eq.{post_url}", "limit": "1"},
                     timeout=10)
    data = r.json()
    return data[0] if data else None


def find_post_by_name_platform(campaign_id: str, name: str, platform: str) -> dict | None:
    """URL 교체 시 이름+플랫폼으로 기존 레코드 찾기."""
    r = requests.get(f"{REST}/campaign_posts", headers=HEADERS,
                     params={"select": "id,brand_id,post_url",
                             "campaign_id": f"eq.{campaign_id}",
                             "influencer_name": f"eq.{name}",
                             "platform": f"eq.{platform}",
                             "limit": "1"},
                     timeout=10)
    data = r.json()
    return data[0] if data else None


def create_post(brand_id: str, payload: dict) -> bool:
    r = requests.post(f"{REST}/campaign_posts",
                      headers={**HEADERS, "Prefer": "return=minimal"},
                      json={"brand_id": brand_id, **payload},
                      timeout=15)
    return r.status_code in (200, 201)


def update_post(post_id: str, brand_id: str, payload: dict) -> bool:
    r = requests.patch(f"{REST}/campaign_posts",
                       headers={**HEADERS, "Prefer": "return=minimal"},
                       params={"id": f"eq.{post_id}", "brand_id": f"eq.{brand_id}"},
                       json=payload,
                       timeout=15)
    return r.status_code in (200, 204)


def save_participant_count(campaign_id: str, count: int) -> None:
    requests.patch(f"{REST}/campaigns",
                   headers={**HEADERS, "Prefer": "return=minimal"},
                   params={"id": f"eq.{campaign_id}"},
                   json={"participant_count": count},
                   timeout=10)


# ── 파싱 헬퍼 ─────────────────────────────────────────────────────────────────

def _parse_date(val) -> str | None:
    s = str(val or "").strip()
    s = re.sub(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", r"\1-\2-\3", s)
    try:
        from datetime import datetime
        return str(datetime.strptime(s, "%Y-%m-%d").date())
    except Exception:
        return None


def _int(v) -> int:
    try:
        s = str(v).strip()
        return int(float(s)) if s and s.lower() not in ("", "nan", "none", "-") else 0
    except Exception:
        return 0


def _clean(v) -> str:
    s = str(v or "").strip()
    return "" if s.lower() in ("nan", "none", "-") else s


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", required=True, help="Google Sheets URL")
    parser.add_argument("--campaign", required=True, help="캠페인 이름 (일부 입력 가능)")
    parser.add_argument("--overwrite", action="store_true", help="기존 데이터 덮어쓰기 + URL 교체")
    parser.add_argument("--participants", type=int, default=0,
                        help="발송 인원 수 직접 지정 (0=시트 행수 사용)")
    args = parser.parse_args()

    # 캠페인 찾기
    campaigns = get_campaigns()
    matched = [c for c in campaigns if args.campaign.lower() in c["name"].lower()]
    if not matched:
        print(f"캠페인을 찾을 수 없습니다: {args.campaign}")
        print("존재하는 캠페인:")
        for c in campaigns: print(f"  - {c['name']}")
        sys.exit(1)
    if len(matched) > 1:
        print("여러 캠페인이 매칭됩니다:")
        for c in matched: print(f"  - {c['name']}")
        sys.exit(1)

    campaign = matched[0]
    campaign_id = campaign["id"]
    brand_id    = campaign["brand_id"]
    print(f"캠페인: {campaign['name']} (brand_id={brand_id[:8]}...)")

    # Google Sheet CSV 다운로드
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", args.sheet)
    if not m:
        print("올바른 Google Sheets URL이 아닙니다.")
        sys.exit(1)
    sheet_id = m.group(1)
    gid_m = re.search(r"[#&?]gid=(\d+)", args.sheet)
    gid = gid_m.group(1) if gid_m else "0"
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

    print(f"시트 다운로드 중...")
    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.content.decode("utf-8-sig")))
    df.columns = [c.strip().lower() for c in df.columns]
    print(f"  {len(df)}행 로드됨")

    # 컬럼 매핑
    def _find_col(aliases):
        for a in aliases:
            if a in df.columns:
                return a
        return None

    mapped = {field: _find_col(aliases) for field, aliases in COL_ALIASES.items()}

    if not mapped.get("name"):
        print("필수 컬럼 누락: name (인플루언서명)")
        sys.exit(1)

    def _val(r, field, default=0):
        col = mapped.get(field)
        return r[col] if col and col in r.index else default

    # 이관 실행
    total   = len(df)
    p_count = args.participants if args.participants > 0 else total
    created = updated = skipped = errors = 0

    print(f"\n이관 시작 (총 {total}행, {'덮어쓰기' if args.overwrite else '신규만'})\n")

    for i, (_, r) in enumerate(df.iterrows(), 1):
        name = _clean(_val(r, "name", ""))
        pct  = i / total * 100
        print(f"[{i}/{total}] ({pct:.0f}%) {name}", end=" ", flush=True)

        if not name or name.lower() in _HEADER_NAMES:
            print("→ 건너뜀 (헤더/빈값)")
            skipped += 1
            continue

        ig_url   = _clean(_val(r, "ig_url",   ""))
        tt_url   = _clean(_val(r, "tt_url",   ""))
        x_url    = _clean(_val(r, "x_url",    ""))
        lips_url = _clean(_val(r, "lips_url", ""))
        upload_date = _parse_date(_val(r, "upload_day", ""))

        if not any([ig_url, tt_url, x_url, lips_url]):
            print("→ URL 없음")
            skipped += 1
            continue

        # 지표
        tt_m = {
            "views": _int(_val(r,"tt_views") or _val(r,"views")),
            "likes": _int(_val(r,"tt_likes") or _val(r,"likes")),
            "comments": _int(_val(r,"tt_comments") or _val(r,"comments")),
            "saves": _int(_val(r,"tt_saves") or _val(r,"saves")),
            "shares": _int(_val(r,"tt_shares") or _val(r,"shares")),
        }
        has_ig = any(_val(r, k) for k in ("ig_views","ig_likes","ig_comments","ig_saves"))
        ig_m = {
            "views":    _int(_val(r,"ig_views")    or (0 if has_ig or tt_url else _val(r,"views"))),
            "likes":    _int(_val(r,"ig_likes")    or (0 if has_ig or tt_url else _val(r,"likes"))),
            "comments": _int(_val(r,"ig_comments") or (0 if has_ig or tt_url else _val(r,"comments"))),
            "saves":    _int(_val(r,"ig_saves")    or (0 if has_ig or tt_url else _val(r,"saves"))),
            "shares":   _int(_val(r,"ig_shares")   or 0),
        }
        has_x = any(_val(r, k) for k in ("x_views","x_likes","x_comments"))
        x_m = {
            "views":    _int(_val(r,"x_views")    or (0 if has_x or tt_url or ig_url else _val(r,"views"))),
            "likes":    _int(_val(r,"x_likes")    or (0 if has_x or tt_url or ig_url else _val(r,"likes"))),
            "comments": _int(_val(r,"x_comments") or 0),
            "saves":    _int(_val(r,"x_saves")    or 0),
            "shares":   _int(_val(r,"x_shares")   or 0),
        }
        has_other = any(_val(r, k) for k in ("other_views","other_likes","lips_views"))
        other_m = {
            "views":    _int(_val(r,"other_views")    or _val(r,"lips_views")    or 0),
            "likes":    _int(_val(r,"other_likes")    or _val(r,"lips_likes")    or 0),
            "comments": _int(_val(r,"other_comments") or _val(r,"lips_comments") or 0),
            "saves":    _int(_val(r,"other_saves")    or _val(r,"lips_saves")    or 0),
            "shares":   _int(_val(r,"other_shares")   or _val(r,"lips_shares")  or 0),
        }

        to_process = []
        if tt_url:   to_process.append(("tiktok",    tt_url,   tt_m))
        if ig_url:   to_process.append(("instagram", ig_url,   ig_m))
        if x_url:    to_process.append(("x",         x_url,    x_m))
        if lips_url: to_process.append(("other",     lips_url, other_m))

        row_ok = True
        for platform, url, metrics in to_process:
            payload = {
                "campaign_id":     campaign_id,
                "influencer_name": name,
                "platform":        platform,
                "post_url":        url,
                "upload_date":     upload_date,
                **metrics,
            }

            existing_by_url = find_post_by_url(url)

            if existing_by_url:
                if args.overwrite:
                    ok = update_post(existing_by_url["id"], existing_by_url["brand_id"],
                                     {k: v for k, v in payload.items() if k != "campaign_id"})
                    if ok: updated += 1
                    else:  row_ok = False
                else:
                    skipped += 1
                continue

            if args.overwrite:
                # URL이 바뀐 경우 — 이름+플랫폼으로 찾아서 URL까지 교체
                existing_by_name = find_post_by_name_platform(campaign_id, name, platform)
                if existing_by_name:
                    ok = update_post(existing_by_name["id"], brand_id, payload)
                    if ok:
                        updated += 1
                        continue
                    else:
                        row_ok = False
                        continue

            # 완전 신규
            ok = create_post(brand_id, payload)
            if ok: created += 1
            else:  row_ok = False

        if row_ok:
            print(f"✅")
        else:
            print(f"❌ 오류")
            errors += 1

    # 발송 인원 저장
    save_participant_count(campaign_id, p_count)

    print(f"\n== 완료 ==")
    print(f"  신규: {created}개  업데이트: {updated}개  건너뜀: {skipped}개  오류: {errors}개")
    print(f"  발송 인원: {p_count}명 저장됨")


if __name__ == "__main__":
    main()
