"""브랜드 랭킹용 Google Sheet(TikTok UGC 콘텐츠 export) → Supabase 이관.

시트 형식: 브랜드명을 탭 이름으로 하고, 각 탭은 TikTok 스크래핑 결과를
"channel/username", "likes", "hashtags/0..N", "poi/regionCode" 같은
평탄화된(flatten) 컬럼으로 담고 있다 (사용자가 Apify 콘솔에서 직접
수집해 Google Sheet로 export한 데이터).

사용법:
    python scripts/import_brand_ranking_sheet.py <SHEET_ID>
    python scripts/import_brand_ranking_sheet.py <SHEET_ID> --dry-run   # 저장 없이 미리보기만
"""
import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
import pandas as pd
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL, SUPABASE_KEY 환경변수가 필요합니다.")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).strip()
    return s if s and s.lower() not in ("nan", "none") else None


def _int(v) -> int:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def map_row(row: dict, brand_name: str) -> dict | None:
    cid = _clean(row.get("id"))
    if not cid:
        return None

    hashtags = []
    i = 0
    while f"hashtags/{i}" in row:
        h = _clean(row.get(f"hashtags/{i}"))
        if h:
            hashtags.append(h)
        i += 1

    return {
        "id": cid,
        "brand_name": brand_name,
        "platform": "tiktok",
        "post_url": _clean(row.get("postPage")),
        "video_url": _clean(row.get("video/url")),
        "title": _clean(row.get("title")),
        "channel_username": _clean(row.get("channel/username")),
        "channel_followers": _int(row.get("channel/followers")),
        "channel_verified": _bool(row.get("channel/verified")),
        "likes": _int(row.get("likes")),
        "comments": _int(row.get("comments")),
        "shares": _int(row.get("shares")),
        "views": _int(row.get("views")),
        "hashtags": hashtags or None,
        "region_code": _clean(row.get("poi/regionCode")),
        "city_name": _clean(row.get("poi/cityName")),
        "input_source": _clean(row.get("inputSource")),
        "uploaded_at": _clean(row.get("uploadedAtFormatted")),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sheet_id", help="Google Sheet ID")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 미리보기만")
    args = parser.parse_args()

    url = f"https://docs.google.com/spreadsheets/d/{args.sheet_id}/export?format=xlsx"
    print(f"시트 다운로드 중: {url}")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    xls = pd.ExcelFile(io.BytesIO(resp.content))
    print(f"탭 목록: {xls.sheet_names}\n")

    total_saved = 0
    for brand_name in xls.sheet_names:
        df = xls.parse(brand_name)
        rows = [map_row(r.to_dict(), brand_name) for _, r in df.iterrows()]
        rows = [r for r in rows if r]

        # 같은 id가 여러 검색어(inputSource)로 중복 수집된 경우 dedup (마지막 값 유지)
        dedup: dict[str, dict] = {}
        for r in rows:
            dedup[r["id"]] = r
        n_dupes = len(rows) - len(dedup)
        rows = list(dedup.values())

        print(f"[{brand_name}] {len(rows)}개 유효 행 (원본 {len(df)}행, 중복 제거 {n_dupes}건)")

        if args.dry_run:
            if rows:
                sample = rows[0]
                print(f"  샘플: {sample['channel_username']} | likes={sample['likes']} "
                      f"views={sample['views']} hashtags={sample['hashtags'][:3] if sample['hashtags'] else []}")
            continue

        CHUNK = 500
        saved = 0
        for i in range(0, len(rows), CHUNK):
            chunk = rows[i:i + CHUNK]
            sb.table("brand_ranking_content").upsert(chunk, on_conflict="id").execute()
            saved += len(chunk)
        total_saved += saved
        print(f"  저장 완료: {saved}개")

    if args.dry_run:
        print("\n[dry-run] 저장하지 않았습니다. --dry-run 없이 다시 실행하면 저장됩니다.")
    else:
        print(f"\n총 저장: {total_saved}개")


if __name__ == "__main__":
    main()
