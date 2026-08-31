import streamlit as st
from utils.auth import sidebar_user_info
from utils.supabase_client import get_user_profile

sidebar_user_info()

user = st.session_state.user
st.title("인플루언서 관리 대시보드")
st.markdown("사이드바 메뉴에서 원하는 기능을 선택하세요.")
st.divider()

col1, col2, col3, col4 = st.columns(4)
with col1:
    with st.container(border=True):
        st.markdown("### 🎬 탐색")
        st.caption("인플루언서 탐색 및 즐겨찾기")
        st.page_link("pages/_browse.py", label="이동 →")
with col2:
    with st.container(border=True):
        st.markdown("### 📋 캠페인")
        st.caption("캠페인 생성 및 후보 관리")
        st.page_link("pages/5_campaigns.py", label="이동 →")
with col3:
    with st.container(border=True):
        st.markdown("### 👥 즐겨찾기")
        st.caption("브랜드별 즐겨찾기 인플루언서")
        st.page_link("pages/2_influencers.py", label="이동 →")
with col4:
    with st.container(border=True):
        st.markdown("### 📊 콘텐츠 성과")
        st.caption("게시물별 업로드 성과 관리")
        st.page_link("pages/6_content_performance.py", label="이동 →")

# 어드민 전용 카드
profile = get_user_profile(user.id)
if profile.get("role") == "admin":
    st.divider()
    st.caption("🔧 관리자 전용")
    ac1, ac2, _ = st.columns([1, 1, 2])
    with ac1:
        with st.container(border=True):
            st.markdown("### 📊 어드민 대시보드")
            st.caption("수집 현황 및 유저 계정 관리")
            st.page_link("pages/_dashboard.py", label="이동 →")
    with ac2:
        with st.container(border=True):
            st.markdown("### 🏢 브랜드 관리")
            st.caption("브랜드 생성 및 설정")
            st.page_link("pages/_brands.py", label="이동 →")
