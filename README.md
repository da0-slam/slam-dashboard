# 🎯 Slam Global 인플루언서 관리 대시보드

인플루언서 마케팅 캠페인의 전 과정을 한 곳에서 관리하는 대시보드입니다.  
인플루언서 탐색 → 캠페인 배정 → 콘텐츠 성과 추적까지 통합 지원합니다.

**배포 환경**: Railway (자동 배포) · **DB/인증**: Supabase · **프레임워크**: Streamlit

---

## 📌 주요 기능 한눈에 보기

| 페이지 | 기능 요약 |
|--------|-----------|
| 🏠 홈 | 최근 캠페인 현황 및 콘텐츠 성과 요약 카드 |
| 🔍 인플루언서 탐색 | 전체 인플루언서 썸네일 그리드 탐색 |
| ⭐ 즐겨찾기 | 브랜드별 인플루언서 후보 관리 |
| 📋 캠페인 관리 | 캠페인 생성·수정·삭제 및 인플루언서 배정 |
| 📊 콘텐츠 성과 관리 | 게시물별 성과 지표 추적 및 시각화 |
| 📊 어드민 대시보드 | 수집 현황 및 유저 관리 (관리자 전용) |

---

## 🔍 페이지별 상세 기능

### 🔐 로그인 / 회원가입

- 이메일 + 비밀번호 로그인 및 회원가입
- **Google · 카카오** 소셜 로그인 (OAuth 2.0 PKCE)
- 회원가입 시 이메일 인증 확인 후 활성화
- 브랜드 자동 연결 (회원가입 시 브랜드명 입력)

---

### 🔍 인플루언서 탐색 (Browse)

인플루언서 콘텐츠를 썸네일 그리드 형태로 탐색합니다.

- **그레이드 필터**: S/A/B/C 등급별 필터링
- **연도 필터**: 업로드 연도별 필터링
- **키워드 검색**: 인플루언서 계정명으로 검색
- **캡션 검색**: 영상 캡션 내 키워드 검색
- **언어 필터**: 한국어 / 영어 / 일본어 등 콘텐츠 언어별 필터링
- **⭐ 즐겨찾기만 보기**: 현재 브랜드에서 즐겨찾기한 인플루언서만 표시
- **정렬**: Rank / ER% / 최신순 / 오래된순
- **페이지네이션**: 페이지당 48개, 이전/다음 내비게이션
- **썸네일 클릭**: 해당 영상 URL 바로 이동 (썸네일 우선 노출 — Supabase Storage 저장 영상 최우선)
- **전체 영상 보기**: 인플루언서의 모든 영상 목록 + 평균 조회수 / 평균 ER 팝업
- **💬 메모/댓글**: 카드마다 댓글 버튼 — 브랜드 내 팀원 간 공유 댓글 (Figma 스타일 UI)

---

### ⭐ 즐겨찾기 (인플루언서 관리)

브랜드별 인플루언서 후보를 관리합니다.

- 인플루언서 후보 추가 및 상태 변경
  - `candidate` (검토 중) → `confirmed` (확정) / `rejected` (제외)
- 캠페인 연결 가능
- 브랜드 접근 비밀번호 설정으로 외부 공유 가능

---

### 📋 캠페인 관리

캠페인 생성부터 인플루언서 배정까지 관리합니다.

- **캠페인 CRUD**: 캠페인 생성·수정·삭제
- **인플루언서 배정**: 즐겨찾기 목록에서 캠페인에 배정
- **상태 관리**: 후보 → 확정 → 제외 상태 추적 (그리드/리스트 뷰)
- **초대 링크**: 항상 표시되는 캠페인 공유 URL (토글 없이 바로 복사 가능)
- **💬 메모/댓글**: 인플루언서 카드마다 댓글 버튼 — 같은 브랜드/캠페인 팀원만 조회 가능
- **CSV 일괄 등록**: 인플루언서 목록을 CSV로 한 번에 캠페인에 추가
  - 유연한 컬럼 자동 인식 (계정명, URL, 플랫폼 등)

---

### 📊 콘텐츠 성과 관리

캠페인에 참여한 인플루언서의 게시물 성과를 추적합니다.

#### Tab 1 — 성과 대시보드
- **KPI 카드**: 총 조회수 · 좋아요 · 댓글 · 저장 · 공유 · 평균 참여율
- **인플루언서별 조회수 TOP 10** 바 차트
- **플랫폼 비교** (TikTok vs Instagram) 바 차트
- **TT + IG 동시 참여 인플루언서** 비교 테이블
- 전체 게시물 목록 테이블 (URL 클릭 이동)

#### Tab 2 — 인플루언서 요약
- 인플루언서별 게시물 수, 총 조회수/좋아요/댓글/저장/공유 집계
- 최고 성과 게시물 URL 링크

#### Tab 3 — 우수 콘텐츠 추천
- 조회수 TOP 5 / 참여율 TOP 5 / 저장 수 TOP 5 / 댓글 TOP 5

#### Tab 4 — 게시물 관리
- **직접 추가**: 인플루언서명, 플랫폼, URL, 날짜, 지표 수동 입력
- **수정 / 삭제**: 기존 게시물 수정 및 삭제
- **Google Sheet CSV 이관**: 구글 시트 데이터를 CSV로 내보내 일괄 등록
  - **TikTok + Instagram 동시 지원**: `tt_url` + `ig_url` 모두 입력 시 각각 별도 게시물로 등록
  - **플랫폼별 지표 분리**: `tt_views/tt_likes/…` · `ig_views/ig_likes/…` 컬럼 자동 인식
  - **구글 시트 컬럼 자동 인식**: `Posting URL (TT)`, `Views`, `Likes♥`, `Comments`, `Saves`, `Posting URL (IG)`, `Views(IG)`, `Likes♥(IG)`, `Comments(IG)` 등
  - **구형 단일 컬럼 형식** (`views/likes/…`)도 하위 호환 지원
  - **덮어쓰기 모드**: 기존 URL이 있을 경우 지표를 업데이트 (재이관 시 유용)

#### 사이드바 필터 (모든 탭 공통)
- 캠페인, 플랫폼, 업로드 기간, 인플루언서명, URL 필터
- 조회수 / 참여율 / 좋아요 / 저장 / 댓글 기준 정렬

---

### 📊 어드민 대시보드 (관리자 전용)

- **파이프라인 현황**: 인플루언서 수집 상태 파이 차트 (완료 / 처리중 / 실패)
- **조회수 TOP 20** 콘텐츠 바 차트 및 상세 테이블
- **유저 브랜드 배정**: 전체 유저 목록 조회 및 브랜드 재배정 (계정 연결 오류 수정용)

---

## 🛠 기술 스택

| 구분 | 스택 |
|------|------|
| 프론트엔드 | Streamlit |
| 데이터베이스 / 인증 | Supabase (PostgreSQL + Auth) |
| 배포 | Railway (Nixpacks, Python 3.11) |
| 시각화 | Plotly Express, Streamlit native charts |
| HTTP 클라이언트 | requests (Railway HTTP/2 StreamReset 우회) |

---

## 📁 프로젝트 구조

```
slam-dashboard/
├── app.py                       # 진입점 — 로그인 · 회원가입 · OAuth 처리
├── pages/
│   ├── 2_influencers.py         # ⭐ 즐겨찾기 (brand_selections)
│   ├── 4_browse.py              # 🔍 인플루언서 탐색 (썸네일 그리드 + 페이지네이션)
│   ├── 5_campaigns.py           # 📋 캠페인 관리 (CRUD + CSV 일괄 등록)
│   └── 6_content_performance.py # 📊 콘텐츠 성과 관리 (성과 대시보드 + CSV 이관)
├── _hidden_pages/
│   ├── dashboard.py             # 📊 어드민 대시보드 (수집 현황 + 유저 관리)
│   └── brands.py                # 브랜드 관리 (관리자용)
├── utils/
│   ├── supabase_client.py       # Supabase 클라이언트, 전체 DB 헬퍼 함수
│   ├── auth.py                  # require_auth, 사이드바 유저 정보
│   ├── session.py               # 세션 저장·복원 (메모리 + Supabase DB 이중 저장)
│   └── notes_ui.py              # 인플루언서 메모/댓글 공통 다이얼로그 (Figma 스타일)
├── migrations/
│   ├── 008_browse_view_thumbnail_priority.sql  # v_browse_contents 썸네일 우선순위
│   └── 009_sessions_table.sql                  # slam_sessions 세션 영구 저장 테이블
├── scripts/
│   ├── backfill_thumbnails.py   # 썸네일 미수집 건 일괄 보완 (tikwm.com 우회 포함)
│   └── sync_instagram_from_usdb.py  # US_DB → influencer_master Instagram 데이터 동기화
├── requirements.txt
└── railway.toml
```

---

## ⚙️ 환경변수 설정

Railway Variables (또는 로컬 `.env`)에 아래 변수를 **각각 별도 항목으로** 추가하세요.

| 변수명 | 설명 |
|--------|------|
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_KEY` | Supabase service_role 키 (JWT 토큰만, 개행 없이) |
| `APIFY_TOKEN` | Apify API 토큰 (콘텐츠 자동 수집용) |
| `SITE_URL` | 배포 URL (OAuth 리디렉션용, 예: `https://your-app.up.railway.app`) |

> **주의**: `SUPABASE_KEY`에는 JWT 토큰 값만 입력하세요. 여러 변수를 한 필드에 붙여넣으면 인증 오류가 발생합니다.

---

## 💻 로컬 실행

```bash
pip install -r requirements.txt
# .env 파일에 위 환경변수 작성 후
streamlit run app.py
```

---

## 🚀 Railway 배포

```bash
git push origin main
```

`railway.toml`에 빌드·시작 명령이 정의되어 있어 푸시 후 자동 배포됩니다 (약 2~3분 소요).

---

## 🗄 Supabase 테이블 구조

| 테이블 | 용도 |
|--------|------|
| `influencer_master` | 인플루언서 기본 정보, Apify 수집 상태 |
| `koc_contents` | 수집된 콘텐츠 (조회수, 좋아요, 썸네일 URL 등) |
| `brands` | 브랜드 정보 |
| `brand_selections` | 브랜드별 인플루언서 즐겨찾기 |
| `campaigns` | 캠페인 정보 |
| `campaign_selections` | 캠페인별 인플루언서 배정 및 상태 |
| `campaign_posts` | 캠페인 게시물 성과 지표 (views, likes, comments, saves, shares) |
| `user_profiles` | 유저 역할(admin/brand_user) · 브랜드 연결 |
| `influencer_notes` | 브랜드 공유 메모/댓글 (인플루언서 × 브랜드 스코프) |
| `slam_sessions` | 서버 재시작 후 로그인 유지를 위한 세션 영구 저장 |

---

## 🔧 알려진 이슈 및 해결 내역

| 이슈 | 원인 | 해결 방법 |
|------|------|-----------|
| Railway HTTP/2 StreamReset | Supabase Python SDK와 Railway 네트워크 충돌 | Auth REST API를 `requests` 라이브러리로 직접 호출 |
| SUPABASE_KEY 개행 문자 | 멀티라인 env var 복사 시 개행 포함 | `_clean_env()` 함수로 첫 번째 줄만 사용 |
| 인플루언서 탐색 누락 (Supabase 1000행 제한) | PostgREST 기본 `max_rows=1000` 서버 캡 | `.range()` 페이지네이션 루프로 전체 데이터 조회 |
| 좋아요 0으로 저장 | 구글 시트 `Likes♥` 컬럼의 특수문자(`♥`)가 alias에 미포함 | `likes♥`, `likes♥(ig)` alias 추가 + 덮어쓰기 모드 제공 |
| 테스트 계정 캠페인 미표시 | 동일 브랜드명으로 신규 브랜드 생성되어 brand_id 불일치 | 어드민 대시보드 유저 브랜드 재배정 기능으로 수동 수정 |
| Railway 재배포 시 로그인 초기화 | Supabase refresh token rotation — 사용 후 구 토큰 무효화되나 DB 미업데이트 | 복원 성공 시 `_db_update_refresh()`로 새 토큰을 즉시 DB에 갱신 |
| TikTok 썸네일 수집 실패 (지역 제한) | oEmbed API가 지역 제한 영상에 400 반환 | tikwm.com API를 fallback으로 추가해 우회 수집 |
