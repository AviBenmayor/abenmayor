import os

import streamlit as st

from theme import inject_css

# Login is disabled for now — flip back to True to restore the gate.
AUTH_ENABLED = os.environ.get("DASH_AUTH_ENABLED", "false").lower() == "true"

USERNAME = os.environ.get("DASH_USERNAME", "avi_interview")
PASSWORD = os.environ.get("DASH_PASSWORD", "you_should_hire!")


def login_gate() -> None:
    inject_css()
    if not AUTH_ENABLED:
        return
    if st.session_state.get("authed"):
        return
    left, mid, right = st.columns([1, 1.3, 1])
    with mid:
        st.markdown(
            '<div style="height:12vh"></div>'
            '<div class="mag-kicker">Manhattan Athletic Group</div>',
            unsafe_allow_html=True,
        )
        st.title("Desk Dashboard")
        st.caption("Sign in to view the desk's P&L, hold, and cash-at-exchange views.")
        with st.container(border=True):
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", use_container_width=True)
        if submitted:
            if u == USERNAME and p == PASSWORD:
                st.session_state["authed"] = True
                st.rerun()
            else:
                st.error("Incorrect username or password.")
    st.stop()
