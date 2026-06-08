# Slam Global 인플루언서 관리 대시보드

Streamlit 기반의 인플루언서 캠페인 관리 대시보드입니다. Railway에 배포되며, Supabase를 데이터베이스 및 인증 백엔드로 사용합니다.

## 주요 기능

- **인증** — 이메일/비밀번호 로그인·회원가입, Google/카카오 소셜 로그인 (OAuth)
- **인플루언서 탐색** — 플랫폼별 필터링, 조회수 기준 콘텐츠 정렬
- **즐겨찾기** — 브랜드별 인플루언서 후보 관리 (candidate → confirmed/rejected)
- **캠페인** — 캠페인 생성·수정·삭제, 캠페인별 인플루언서 배정 및 상태 관리

## 기술 스택

| 구분 | 스택 |
|------|------|
| 프론트엔드 | Streamlit |
| 데이터베이스 / 인증 | Supabase (PostgreSQL + Auth) |
| 배포 | Railway (Nixpacks, Python 3.11) |
| HTTP 클라이언트 | requests (Railway HTTP/2 StreamReset 우회) |

## 프로젝트 구조

```
slam-dashboard/
├── app.py                  # 진입점, 로그인·회원가입 UI
├── pages/
│   ├── 2_influencers.py    # 즐겨찾기 (brand_selections)
│   ├── 4_browse.py         # 인플루언서 탐색
│   └── 5_campaigns.py      # 캠페인 관리
├── _hidden_pages/
│   ├── brands.py           # 브랜드 관리 (관리자용)
│   └── dashboard.py        # 파이프라인 대시보드
├── utils/
│   ├── supabase_client.py  # Supabase 클라이언트, DB 헬퍼, Auth REST 래퍼
│   ├── auth.py             # require_auth, 사이드바 유저 정보
│   └── session.py          # 서버 메모리 세션 저장·복원 (새로고침 대응)
├── requirements.txt
└── railway.toml
```

## 환경변수 설정

Railway Variables (또는 로컬 `.env`)에 아래 변수를 **각각 별도 항목으로** 추가하세요.

| 변수명 | 설명 |
|--------|------|
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_KEY` | Supabase service_role 키 (JWT 토큰만, 개행 없이) |
| `APIFY_TOKEN` | Apify API 토큰 |
| `SITE_URL` | 배포 URL (OAuth 리디렉션용, 예: `https://your-app.up.railway.app`) |

> **주의**: `SUPABASE_KEY`에는 JWT 토큰 값만 입력하세요. 여러 환경변수를 한 필드에 붙여넣으면 인증 오류가 발생합니다.

## 로컬 실행

```bash
pip install -r requirements.txt
# .env 파일에 위 환경변수 작성 후
streamlit run app.py
```

## Railway 배포

```bash
git push origin main
```

`railway.toml`에 빌드·시작 명령이 정의되어 있어 자동 배포됩니다.

## Supabase 테이블 구조

| 테이블 | 용도 |
|--------|------|
| `influencer_master` | 인플루언서 기본 정보, Apify 수집 상태 |
| `koc_contents` | 콘텐츠 (조회수, 좋아요, 썸네일 등) |
| `brands` | 브랜드 정보 |
| `brand_members` | 브랜드-유저 매핑 |
| `brand_selections` | 브랜드별 인플루언서 즐겨찾기 |
| `campaigns` | 캠페인 |
| `campaign_selections` | 캠페인별 인플루언서 배정 |
| `user_profiles` | 유저 역할·브랜드 연결 |

## 알려진 이슈 및 해결 내역

- **Railway HTTP/2 StreamReset**: Supabase Python SDK 대신 `requests` 라이브러리로 Auth REST API 직접 호출하여 우회
- **SUPABASE_KEY 개행 문제**: `_clean_env()` 함수로 env var 첫 번째 줄만 사용하도록 방어 처리
