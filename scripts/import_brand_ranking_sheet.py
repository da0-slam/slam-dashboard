"""브랜드 랭킹용 Google Sheet(TikTok UGC 콘텐츠/댓글 export) → Supabase 이관.

시트 형식: 브랜드명을 탭 이름으로 하고, 각 탭은 TikTok 스크래핑 결과를
"channel/username", "likes", "hashtags/0..N", "poi/regionCode" 같은
평탄화된(flatten) 컬럼으로 담고 있다 (사용자가 Apify 콘솔에서 직접
수집해 Google Sheet로 export한 데이터).

탭 이름이 "{브랜드명}-코멘트" 또는 "{브랜드명}-댓글"로 끝나면 댓글 탭으로
인식해 brand_ranking_comments 테이블(apidojo/tiktok-comments-scraper 형식:
"user/region", "user/language" 등)에 저장한다. 그 외 탭은 콘텐츠 탭으로
인식해 brand_ranking_content 테이블에 저장한다.

사용법:
    python scripts/import_brand_ranking_sheet.py <SHEET_ID>
    python scripts/import_brand_ranking_sheet.py <SHEET_ID> --dry-run   # 저장 없이 미리보기만
    python scripts/import_brand_ranking_sheet.py <SHEET_ID> --exclude-keywords "plastic surgery,phẫu thuật thẩm mỹ"
        # 콘텐츠 탭에서 캡션/해시태그에 이 키워드가 하나라도 포함되면 제외 (콘텐츠 탭에만 적용)
"""
import argparse
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

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


def map_comment_row(row: dict, brand_name: str) -> dict | None:
    cid = _clean(row.get("id"))
    if not cid:
        return None
    return {
        "id": cid,
        "brand_name": brand_name,
        "aweme_id": _clean(row.get("awemeId")),
        "parent_id": _clean(row.get("parentId")),
        "text": _clean(row.get("text")),
        "comment_language": _clean(row.get("commentLanguage")),
        "like_count": _int(row.get("likeCount")),
        "reply_count": _int(row.get("replyCount")),
        "is_author_liked": _bool(row.get("isAuthorLiked")),
        "created_at": _clean(row.get("createdAt")),
        "user_id": _clean(row.get("user/id")),
        "username": _clean(row.get("user/username")),
        "display_name": _clean(row.get("user/displayName")),
        "user_region": _clean(row.get("user/region")),
        "user_language": _clean(row.get("user/language")),
        "input_source": _clean(row.get("inputSource")),
    }


_COMMENT_TAB_SUFFIXES = ("-코멘트", "-댓글")


def _strip_comment_suffix(tab_name: str) -> tuple[str, bool]:
    for suffix in _COMMENT_TAB_SUFFIXES:
        if tab_name.endswith(suffix):
            return tab_name[: -len(suffix)], True
    return tab_name, False


def _matches_excluded(row: dict, keywords: list[str]) -> bool:
    haystack = (row.get("title") or "").lower() + " " + " ".join(row.get("hashtags") or []).lower()
    return any(kw.lower() in haystack for kw in keywords)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sheet_id", help="Google Sheet ID")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 미리보기만")
    parser.add_argument("--only", help="쉼표로 구분한 탭 이름만 처리 (예: '헤브블루,헤브블루-코멘트')")
    parser.add_argument("--exclude-keywords", help="쉼표로 구분한 제외 키워드 (콘텐츠 탭의 캡션/해시태그 대상)")
    args = parser.parse_args()

    exclude_keywords = [k.strip() for k in args.exclude_keywords.split(",")] if args.exclude_keywords else []

    url = f"https://docs.google.com/spreadsheets/d/{args.sheet_id}/export?format=xlsx"
    print(f"시트 다운로드 중: {url}")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    xls = pd.ExcelFile(io.BytesIO(resp.content))
    only_tabs = {t.strip() for t in args.only.split(",")} if args.only else None
    tab_names = [t for t in xls.sheet_names if not only_tabs or t in only_tabs]
    print(f"탭 목록: {xls.sheet_names}")
    print(f"처리할 탭: {tab_names}")
    if exclude_keywords:
        print(f"제외 키워드(콘텐츠 탭만): {exclude_keywords}")
    print()

    total_saved = 0
    for tab_name in tab_names:
        brand_name, is_comment_tab = _strip_comment_suffix(tab_name)
        table_name = "brand_ranking_comments" if is_comment_tab else "brand_ranking_content"
        mapper = map_comment_row if is_comment_tab else map_row

        df = xls.parse(tab_name)
        rows = [mapper(r.to_dict(), brand_name) for _, r in df.iterrows()]
        rows = [r for r in rows if r]

        n_excluded = 0
        if exclude_keywords and not is_comment_tab:
            before = len(rows)
            rows = [r for r in rows if not _matches_excluded(r, exclude_keywords)]
            n_excluded = before - len(rows)

        # 같은 id가 여러 검색어(inputSource)로 중복 수집된 경우 dedup (마지막 값 유지)
        dedup: dict[str, dict] = {}
        for r in rows:
            dedup[r["id"]] = r
        n_dupes = len(rows) - len(dedup)
        rows = list(dedup.values())

        kind = "댓글" if is_comment_tab else "콘텐츠"
        print(f"[{tab_name}] ({kind}, brand={brand_name}) {len(rows)}개 유효 행 (원본 {len(df)}행, "
              f"중복 제거 {n_dupes}건, 키워드 제외 {n_excluded}건)")

        if args.dry_run:
            if rows:
                sample = rows[0]
                if is_comment_tab:
                    print(f"  샘플: {sample['username']} | region={sample['user_region']} "
                          f"lang={sample['user_language']} likes={sample['like_count']}")
                else:
                    print(f"  샘플: {sample['channel_username']} | likes={sample['likes']} "
                          f"views={sample['views']} hashtags={sample['hashtags'][:3] if sample['hashtags'] else []}")
            continue

        CHUNK = 500
        saved = 0
        for i in range(0, len(rows), CHUNK):
            chunk = rows[i:i + CHUNK]
            sb.table(table_name).upsert(chunk, on_conflict="id").execute()
            saved += len(chunk)
        total_saved += saved
        print(f"  저장 완료: {saved}개")

    if args.dry_run:
        print("\n[dry-run] 저장하지 않았습니다. --dry-run 없이 다시 실행하면 저장됩니다.")
    else:
        print(f"\n총 저장: {total_saved}개")


if __name__ == "__main__":
    main()
