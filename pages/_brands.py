import streamlit as st
from utils.auth import require_auth, sidebar_user_info
from utils.supabase_client import (
    get_brands, create_brand, update_brand, delete_brand,
    set_brand_access_password,
)

st.set_page_config(page_title="브랜드사 관리", page_icon="🏢", layout="wide")

require_auth()
sidebar_user_info()

st.title("🏢 브랜드사 관리")

if "editing_brand" not in st.session_state:
    st.session_state.editing_brand = None
if "confirm_delete" not in st.session_state:
    st.session_state.confirm_delete = None


def _brand_fields(prefix: str, defaults: dict):
    name = st.text_input("브랜드명 *", value=defaults.get("name", ""), key=f"{prefix}_name")
    c1, c2 = st.columns(2)
    with c1:
        category = st.text_input("카테고리", value=defaults.get("category", ""), key=f"{prefix}_cat")
        contact_name = st.text_input("담당자", value=defaults.get("contact_name", ""), key=f"{prefix}_cname")
    with c2:
        contact_email = st.text_input(
            "담당자 이메일", value=defaults.get("contact_email", ""), key=f"{prefix}_cemail"
        )
    notes = st.text_area("메모", value=defaults.get("notes", ""), key=f"{prefix}_notes", height=80)
    return {
        "name": name,
        "category": category,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "notes": notes,
    }


tab_list, tab_add = st.tabs(["📋 브랜드 목록", "➕ 새 브랜드 추가"])

# ─── 브랜드 목록 ─────────────────────────────────────────────────────────────
with tab_list:
    brands = get_brands()

    if not brands:
        st.info("등록된 브랜드사가 없습니다. '새 브랜드 추가' 탭에서 추가하세요.")
    else:
        st.caption(f"총 {len(brands)}개 브랜드사")

        for brand in brands:
            bid = brand["id"]
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
                with c1:
                    cat = f" · {brand['category']}" if brand.get("category") else ""
                    st.markdown(f"**{brand['name']}**{cat}")
                    parts = []
                    if brand.get("contact_name"):
                        parts.append(f"담당자: {brand['contact_name']}")
                    if brand.get("contact_email"):
                        parts.append(brand["contact_email"])
                    if parts:
                        st.caption("  |  ".join(parts))
                    if brand.get("notes"):
                        st.caption(f"📝 {brand['notes']}")
                with c2:
                    if st.button("✏️ 수정", key=f"edit_{bid}", use_container_width=True):
                        st.session_state.editing_brand  = brand
                        st.session_state.confirm_delete = None
                        st.session_state.pop(f"reset_pw_{bid}", None)
                with c3:
                    if st.button("🔑 비밀번호", key=f"pw_{bid}", use_container_width=True):
                        st.session_state[f"reset_pw_{bid}"] = True
                        st.session_state.editing_brand  = None
                        st.session_state.confirm_delete = None
                with c4:
                    if st.button("🗑️ 삭제", key=f"del_{bid}", use_container_width=True):
                        st.session_state.confirm_delete = bid
                        st.session_state.editing_brand  = None

                # 삭제 확인
                if st.session_state.confirm_delete == bid:
                    st.warning(
                        f"**'{brand['name']}'** 을 삭제하시겠습니까? "
                        "연결된 인플루언서 정보도 함께 삭제됩니다."
                    )
                    d1, d2 = st.columns(2)
                    with d1:
                        if st.button("✅ 삭제 확인", key=f"confirm_del_{bid}", type="primary"):
                            delete_brand(bid)
                            st.session_state.confirm_delete = None
                            st.success("삭제되었습니다.")
                            st.rerun()
                    with d2:
                        if st.button("❌ 취소", key=f"cancel_del_{bid}"):
                            st.session_state.confirm_delete = None
                            st.rerun()

                # 수정 폼
                if (
                    st.session_state.editing_brand
                    and st.session_state.editing_brand["id"] == bid
                ):
                    st.divider()
                    with st.form(f"edit_form_{bid}"):
                        st.subheader("✏️ 브랜드 수정")
                        data = _brand_fields("edit", st.session_state.editing_brand)
                        ec1, ec2 = st.columns(2)
                        with ec1:
                            if st.form_submit_button("💾 저장", use_container_width=True, type="primary"):
                                if not data["name"]:
                                    st.error("브랜드명을 입력하세요.")
                                else:
                                    update_brand(bid, data)
                                    st.session_state.editing_brand = None
                                    st.success("수정되었습니다.")
                                    st.rerun()
                        with ec2:
                            if st.form_submit_button("취소", use_container_width=True):
                                st.session_state.editing_brand = None
                                st.rerun()

                # 캠페인 관리 비밀번호 재설정 폼
                if st.session_state.get(f"reset_pw_{bid}"):
                    st.divider()
                    st.caption("🔑 캠페인 관리 비밀번호 재설정")
                    with st.form(f"reset_pw_form_{bid}"):
                        new_pw  = st.text_input("새 비밀번호", type="password")
                        new_pw2 = st.text_input("비밀번호 확인", type="password")
                        r1, r2  = st.columns(2)
                        with r1:
                            if st.form_submit_button("🔑 재설정", type="primary", use_container_width=True):
                                if not new_pw:
                                    st.error("비밀번호를 입력하세요.")
                                elif new_pw != new_pw2:
                                    st.error("비밀번호가 일치하지 않습니다.")
                                elif len(new_pw) < 4:
                                    st.error("비밀번호는 4자 이상이어야 합니다.")
                                else:
                                    set_brand_access_password(bid, new_pw)
                                    st.session_state.pop(f"reset_pw_{bid}", None)
                                    st.success("캠페인 관리 비밀번호가 재설정되었습니다.")
                                    st.rerun()
                        with r2:
                            if st.form_submit_button("취소", use_container_width=True):
                                st.session_state.pop(f"reset_pw_{bid}", None)
                                st.rerun()

# ─── 새 브랜드 추가 ──────────────────────────────────────────────────────────
with tab_add:
    with st.form("add_form"):
        data = _brand_fields("add", {})
        if st.form_submit_button("➕ 브랜드 추가", use_container_width=True, type="primary"):
            if not data["name"]:
                st.error("브랜드명을 입력하세요.")
            else:
                create_brand(data)
                st.success(f"✅ '{data['name']}' 브랜드사가 추가되었습니다.")
                st.rerun()
