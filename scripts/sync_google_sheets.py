"""캠페인별로 등록된 구글시트를 자동으로 다시 가져와 campaign_posts를 갱신한다.

콘텐츠 성과 관리 페이지의 "구글시트 데이터 이관"과 동일한 파싱/매핑 규칙을
쓰지만, 사람이 버튼을 누르지 않아도 되도록 스케줄러(GitHub Actions, 매일)가
이 스크립트를 실행한다. 이미 값이 있는 지표는 덮어쓰지 않고 빈 값만 채운다
(overwrite=False) — 수동으로 "Apify 재추적"한 값을 자동 동기화가 지우는
사고를 막기 위함이다.

사용법:
    python scripts/sync_google_sheets.py
    python scripts/sync_google_sheets.py --dry-run   # 실제 저장 없이 대상만 출력
"""
import argparse
import io
import os
import re
import sys
from datetime import datetime, timezone

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

from utils.supabase_client import get_supabase, parse_google_sheet_csv, migrate_google_sheet_rows


def _csv_export_url(sheet_url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([^/]+)", sheet_url)
    if not m:
        return None
    sheet_id = m.group(1)
    gid_m = re.search(r"[#&?]gid=(\d+)", sheet_url)
    gid = gid_m.group(1) if gid_m else "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def sync_campaign(sb, campaign: dict, dry_run: bool) -> tuple[int, int]:
    """반환: (생성/갱신된 행 수, 에러 수)"""
    name = campaign.get("name", campaign["id"])
    sheet_url = campaign.get("google_sheet_url") or ""
    csv_url = _csv_export_url(sheet_url)
    if not csv_url:
        print(f"  [건너뜀] {name}: 유효한 구글시트 URL이 아님 ({sheet_url!r})")
        return 0, 1

    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()
    raw_csv = pd.read_csv(io.StringIO(resp.content.decode("utf-8-sig")), dtype=str)

    rows, err = parse_google_sheet_csv(raw_csv)
    if err:
        print(f"  [실패] {name}: {err}")
        return 0, 1

    if dry_run:
        print(f"  [dry-run] {name}: {len(rows)}행 확인됨 (저장 안 함)")
        return len(rows), 0

    created, errors = migrate_google_sheet_rows(
        campaign["id"], campaign["brand_id"], rows,
        overwrite=False, participant_count=len(rows),
    )
    sb.table("campaigns").update(
        {"google_sheet_last_synced_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", campaign["id"]).execute()

    print(f"  [완료] {name}: {created}개 생성/갱신, 오류 {len(errors)}건")
    for e in errors[:5]:
        print(f"      - {e}")
    if len(errors) > 5:
        print(f"      ... 외 {len(errors) - 5}건")

    return created, len(errors)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 대상 캠페인/파싱 결과만 출력")
    args = parser.parse_args()

    sb = get_supabase()
    campaigns = (
        sb.table("campaigns")
        .select("id,brand_id,name,google_sheet_url")
        .eq("google_sheet_auto_sync", True)
        .not_.is_("google_sheet_url", "null")
        .execute()
    ).data or []

    if not campaigns:
        print("자동 동기화가 켜진 캠페인이 없습니다.")
        return

    print(f"자동 동기화 대상: {len(campaigns)}개 캠페인")
    total_created = total_errors = 0
    for c in campaigns:
        try:
            created, errors = sync_campaign(sb, c, args.dry_run)
            total_created += created
            total_errors += errors
        except Exception as e:
            print(f"  [예외] {c.get('name', c['id'])}: {e}")
            total_errors += 1

    print(f"\n총 {len(campaigns)}개 캠페인 처리 완료 — 생성/갱신 {total_created}건, 오류 {total_errors}건")


if __name__ == "__main__":
    main()
