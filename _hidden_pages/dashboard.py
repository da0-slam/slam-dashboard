import streamlit as st
import pandas as pd
import plotly.express as px
from utils.auth import require_auth, sidebar_user_info
from utils.supabase_client import get_pipeline_stats, get_total_content_count, get_top_contents

st.set_page_config(page_title="수집 데이터 대시보드", page_icon="📊", layout="wide")

require_auth()
sidebar_user_info()

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
