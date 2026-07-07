import streamlit as st
from utils.auth import require_auth, sidebar_user_info, block_if_demo
from utils.supabase_client import sign_in, update_user_password, update_user_email

st.set_page_config(page_title="계정 설정", page_icon="⚙️", layout="centered")
user = require_auth()
block_if_demo()
sidebar_user_info()

st.title("⚙️ 계정 설정")
st.divider()

# ── 계정 정보 ──────────────────────────────────────────────────────────────────
st.subheader("계정 정보")
st.text_input("이메일", value=user.email, disabled=True)
st.caption("이메일 변경은 아래 섹션에서 가능합니다.")

st.divider()

# ── 비밀번호 변경 ──────────────────────────────────────────────────────────────
st.subheader("비밀번호 변경")

with st.form("pw_form"):
    cur_pw  = st.text_input("현재 비밀번호", type="password")
    new_pw  = st.text_input("새 비밀번호",   type="password", help="6자 이상 입력해주세요.")
    new_pw2 = st.text_input("새 비밀번호 확인", type="password")
    submitted_pw = st.form_submit_button("비밀번호 변경", use_container_width=True, type="primary")

if submitted_pw:
    if not cur_pw or not new_pw or not new_pw2:
        st.error("모든 항목을 입력해주세요.")
    elif len(new_pw) < 6:
        st.error("새 비밀번호는 6자 이상이어야 합니다.")
    elif new_pw != new_pw2:
        st.error("새 비밀번호가 일치하지 않습니다.")
    elif new_pw == cur_pw:
        st.error("새 비밀번호가 현재 비밀번호와 동일합니다.")
    else:
        with st.spinner("확인 중..."):
            try:
                sign_in(user.email, cur_pw)
            except Exception:
                st.error("현재 비밀번호가 올바르지 않습니다.")
                st.stop()
        with st.spinner("비밀번호 변경 중..."):
            ok, err = update_user_password(new_pw)
        if ok:
            st.success("비밀번호가 변경되었습니다.")
        else:
            st.error(f"변경 실패: {err}")

st.divider()

# ── 이메일 변경 ───────────────────────────────────────────────────────────────
st.subheader("이메일 변경")
st.caption("변경 요청 후 새 이메일로 확인 메일이 발송됩니다. 링크를 클릭해야 적용됩니다.")

with st.form("email_form"):
    new_email  = st.text_input("새 이메일 주소")
    email_pw   = st.text_input("현재 비밀번호 (본인 확인)", type="password")
    submitted_email = st.form_submit_button("이메일 변경 요청", use_container_width=True)

if submitted_email:
    if not new_email or not email_pw:
        st.error("모든 항목을 입력해주세요.")
    elif new_email == user.email:
        st.error("현재 이메일과 동일합니다.")
    elif "@" not in new_email:
        st.error("올바른 이메일 주소를 입력해주세요.")
    else:
        with st.spinner("확인 중..."):
            try:
                sign_in(user.email, email_pw)
            except Exception:
                st.error("비밀번호가 올바르지 않습니다.")
                st.stop()
        with st.spinner("이메일 변경 요청 중..."):
            ok, err = update_user_email(new_email)
        if ok:
            st.success(f"확인 메일을 **{new_email}** 로 발송했습니다. 메일의 링크를 클릭하면 변경이 완료됩니다.")
        else:
            st.error(f"변경 실패: {err}")
