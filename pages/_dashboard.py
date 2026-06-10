import streamlit as st
import pandas as pd
import plotly.express as px
from utils.auth import require_auth, sidebar_user_info
from utils.supabase_client import (
    get_pipeline_stats, get_total_content_count, get_top_contents,
    get_all_user_profiles, get_all_auth_users, get_brands,
    assign_user_to_brand, update_user_role, get_user_profile,
)

st.set_page_config(page_title="수집 데이터 대시보드", page_icon="📊", layout="wide")

user = require_auth()
sidebar_user_info()

# admin 전용 페이지
profile = get_user_profile(user.id)
if profile.get("role") != "admin":
    st.error("관리자 전용 페이지입니다.")
    st.stop()

st.title("📊 수집 데이터 대시보드")

if st.button("새로고침"):
    st.rerun()

# ─── 주요 지표 ────────────────────────────────────────────────────────────────
pipeline_stats = get_pipeline_stats()
total_content = get_total_content_count()
total_influencers = sum(pipeline_stats.values())
done_count = pipeline_stats.get("done", 0)
failed_count = pipeline_stats.get("failed", 0)
pending_count = pipeline_stats.get("pending", 0)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("총 인플루언서", f"{total_influencers:,}명")
with col2:
    pct = f"{done_count / total_influencers * 100:.1f}%" if total_influencers else "0%"
    st.metric("수집 완료", f"{done_count:,}명", delta=pct)
with col3:
    st.metric("총 수집 영상", f"{total_content:,}개")
with col4:
    st.metric("수집 실패", f"{failed_count:,}명")

st.divider()

# ─── 파이프라인 상태 차트 ─────────────────────────────────────────────────────
col_left, col_right = st.columns([1, 2])

STATUS_KO = {
    "done": "완료",
    "pending": "처리중",
    "failed": "실패",
    "no_content": "콘텐츠 없음",
    "미수집": "미수집",
}
STATUS_COLORS = {
    "완료": "#22c55e",
    "처리중": "#f59e0b",
    "실패": "#ef4444",
    "콘텐츠 없음": "#94a3b8",
    "미수집": "#cbd5e1",
}

with col_left:
    st.subheader("파이프라인 상태")
    status_ko = {STATUS_KO.get(k, k): v for k, v in pipeline_stats.items() if v > 0}
    if status_ko:
        df_status = pd.DataFrame(list(status_ko.items()), columns=["상태", "인플루언서 수"])
        fig = px.pie(
            df_status,
            names="상태",
            values="인플루언서 수",
            color="상태",
            color_discrete_map=STATUS_COLORS,
            hole=0.45,
        )
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("데이터가 없습니다.")

with col_right:
    st.subheader("조회수 상위 인플루언서 (Top 10)")
    top_contents = get_top_contents(20)

    if top_contents:
        df_top = pd.DataFrame(top_contents)
        top10 = (
            df_top.groupby("influencer_id")["play_count"]
            .sum()
            .reset_index()
            .nlargest(10, "play_count")
        )
        fig2 = px.bar(
            top10,
            x="play_count",
            y="influencer_id",
            orientation="h",
            text="play_count",
            color="play_count",
            color_continuous_scale="Blues",
            labels={"play_count": "총 조회수", "influencer_id": "인플루언서"},
        )
        fig2.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig2.update_layout(
            margin=dict(t=10, b=10, l=10, r=80),
            height=320,
            showlegend=False,
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("수집된 콘텐츠가 없습니다.")

# ─── 상세 데이터 테이블 ────────────────────────────────────────────────────────
if top_contents:
    st.divider()
    with st.expander("📋 상세 영상 데이터 (조회수 상위 20개)"):
        df_detail = pd.DataFrame(top_contents).rename(
            columns={
                "influencer_id": "인플루언서",
                "play_count": "조회수",
                "like_count": "좋아요",
                "comment_count": "댓글",
                "share_count": "공유",
                "save_count": "저장",
                "posted_at": "게시일",
                "video_url": "영상 URL",
            }
        )
        st.dataframe(
            df_detail,
            use_container_width=True,
            hide_index=True,
            column_config={
                "영상 URL": st.column_config.LinkColumn("영상 URL"),
                "조회수": st.column_config.NumberColumn(format="%d"),
                "좋아요": st.column_config.NumberColumn(format="%d"),
            },
        )

# ─── 유저 관리 ────────────────────────────────────────────────────────────────
st.divider()
st.subheader("👤 유저 계정 관리")

all_profiles     = get_all_user_profiles()
all_auth_users   = get_all_auth_users()
all_brands       = get_brands()
brand_id_to_name = {b["id"]: b["name"] for b in all_brands}
brand_name_to_id = {b["name"]: b["id"] for b in all_brands}

# user_id → email 맵
email_map = {u["id"]: u["email"] for u in all_auth_users}

if not all_profiles:
    st.info("등록된 유저가 없습니다.")
else:
    # ── 유저 현황 테이블 ───────────────────────────────────────────────────────
    df_users = pd.DataFrame(all_profiles)
    df_users["email"]      = df_users["user_id"].map(email_map).fillna("(이메일 없음)")
    df_users["brand_name"] = df_users["brand_id"].map(brand_id_to_name).fillna("미배정")
    df_users["role_label"] = df_users["role"].map({"admin": "🔴 관리자", "brand_user": "🟢 브랜드유저"}).fillna(df_users["role"])

    st.dataframe(
        df_users[["email", "role_label", "brand_name"]].rename(columns={
            "email": "이메일", "role_label": "역할", "brand_name": "브랜드",
        }),
        use_container_width=True,
        hide_index=True,
    )

    # 이메일 → user_id 역방향 맵 (selectbox label용)
    def _label(uid: str) -> str:
        email = email_map.get(uid, "(미등록 사용자)")
        brand = brand_id_to_name.get(all_profiles_map.get(uid, {}).get("brand_id", ""), "미배정")
        role  = all_profiles_map.get(uid, {}).get("role", "")
        return f"{email}  |  {brand}  |  {role}"

    all_profiles_map = {p["user_id"]: p for p in all_profiles}

    st.markdown("---")
    sel_uid = st.selectbox(
        "변경할 계정 선택",
        [p["user_id"] for p in all_profiles],
        format_func=_label,
        key="mgmt_user_sel",
    )
    cur = all_profiles_map.get(sel_uid, {})

    c1, c2, c3 = st.columns(3)

    # ── 역할 변경 ──────────────────────────────────────────────────────────────
    with c1:
        st.markdown("**역할 변경**")
        new_role = st.selectbox(
            "역할",
            ["brand_user", "admin"],
            index=0 if cur.get("role") != "admin" else 1,
            key="mgmt_role",
        )
        if st.button("역할 저장", use_container_width=True, key="role_save"):
            if update_user_role(sel_uid, new_role):
                st.success(f"역할을 **{new_role}** 로 변경했습니다.")
                st.rerun()
            else:
                st.error("변경 실패")

    # ── 브랜드 배정 ────────────────────────────────────────────────────────────
    with c2:
        st.markdown("**브랜드 배정**")
        cur_brand_name = brand_id_to_name.get(cur.get("brand_id", ""), None)
        brand_options  = list(brand_name_to_id.keys())
        default_idx    = brand_options.index(cur_brand_name) if cur_brand_name in brand_options else 0
        new_brand = st.selectbox("브랜드", brand_options, index=default_idx, key="mgmt_brand")
        if st.button("브랜드 저장", use_container_width=True, key="brand_save"):
            if assign_user_to_brand(sel_uid, brand_name_to_id[new_brand]):
                st.success(f"브랜드를 **{new_brand}** 로 배정했습니다.")
                st.rerun()
            else:
                st.error("배정 실패")

    # ── 현재 설정 요약 ─────────────────────────────────────────────────────────
    with c3:
        st.markdown("**현재 설정**")
        st.markdown(f"- 이메일: `{email_map.get(sel_uid, '–')}`")
        st.markdown(f"- 역할: `{cur.get('role', '–')}`")
        st.markdown(f"- 브랜드: `{brand_id_to_name.get(cur.get('brand_id',''), '미배정')}`")
