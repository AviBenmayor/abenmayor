import plotly.graph_objects as go
import streamlit as st

from auth import login_gate
from model import load_venue_cash
from theme import ACCENT, PRIMARY, card_title, hero_row, page_header, style_fig, tone

st.set_page_config(page_title="MAG Cash at Exchange", layout="wide", page_icon="🏦")

login_gate()

vc = load_venue_cash()

# ---------------- sidebar controls ----------------
st.sidebar.markdown('<div class="mag-kicker">Controls</div>', unsafe_allow_html=True)
dates = sorted(vc["as_of"].dt.date.unique())
sel_date = st.sidebar.selectbox(
    "As of date", dates, index=len(dates) - 1, format_func=lambda d: d.isoformat()
)
st.sidebar.caption(
    "The revolver facility limit isn't in the trading data — it's a treasury figure, "
    "not an exchange feed. Enter the real number below; headroom updates against it."
)
revolver_limit = st.sidebar.number_input(
    "Total revolver limit ($)", min_value=0.0, value=40_000.0, step=1_000.0, format="%.0f"
)

view = vc[vc["as_of"].dt.date == sel_date]

# ---------------- header ----------------
page_header(
    "Manhattan Athletic Group",
    "Cash at Exchange",
    "How much capital is deployed where, and how much revolver headroom do we have? "
    "Collateral is venue-specific — cash posted at one exchange cannot back a "
    "position at another — so this view is always broken out by venue first.",
)

total_posted = view["posted_collateral"].sum()
total_free = view["free_cash"].sum()
total_capital = view["total_capital"].sum()
total_revolver = view["revolver_drawn"].sum()
utilization = (total_revolver / total_capital * 100) if total_capital else float("nan")
headroom = revolver_limit - total_revolver

# ---------------- hero ----------------
hero_row(
    [
        {"label": "Total capital deployed", "value": f"${total_capital:,.0f}", "tone": "primary"},
        {"label": "Revolver drawn", "value": f"${total_revolver:,.0f}", "tone": None},
        {"label": "Revolver headroom", "value": f"${headroom:,.0f}", "tone": tone(headroom)},
    ]
)

# ---------------- secondary stat cards ----------------
c1, c2, c3 = st.columns(3)
for col, label, value in [
    (c1, "Posted collateral", f"${total_posted:,.0f}"),
    (c2, "Free cash", f"${total_free:,.0f}"),
    (c3, "Revolver utilization", f"{utilization:.0f}%" if total_capital else "—"),
]:
    with col:
        with st.container(border=True):
            st.metric(label, value)

st.write("")

# ---------------- by venue ----------------
left, right = st.columns([3, 2])

with left:
    with st.container(border=True):
        card_title("Capital by venue")
        fig = go.Figure()
        fig.add_bar(name="Posted collateral", x=view["venue"], y=view["posted_collateral"], marker_color=PRIMARY)
        fig.add_bar(name="Free cash", x=view["venue"], y=view["free_cash"], marker_color=ACCENT)
        fig.update_layout(barmode="stack")
        style_fig(fig)
        fig.update_layout(yaxis_title="$")
        st.plotly_chart(fig, use_container_width=True)

with right:
    with st.container(border=True):
        card_title("Revolver utilization by venue")
        tbl = view[["venue", "posted_collateral", "free_cash", "total_capital", "revolver_drawn"]].copy()
        tbl["utilization_%"] = (tbl["revolver_drawn"] / tbl["total_capital"] * 100).round(0)
        tbl = tbl.rename(columns={
            "venue": "Venue", "posted_collateral": "Posted collateral",
            "free_cash": "Free cash", "total_capital": "Total capital",
            "revolver_drawn": "Revolver drawn",
        })
        st.dataframe(
            tbl.set_index("Venue").style.format("${:,.0f}", subset=[
                "Posted collateral", "Free cash", "Total capital", "Revolver drawn"
            ]).format("{:.0f}%", subset=["utilization_%"]),
            use_container_width=True,
        )

# ---------------- trend ----------------
with st.container(border=True):
    card_title(
        "Capital deployed over time",
        "Posted collateral + free cash by venue, across the full trading window in the data.",
    )
    trend = vc.sort_values("as_of")
    fig = go.Figure()
    for venue, g in trend.groupby("venue"):
        fig.add_scatter(x=g["as_of"], y=g["total_capital"], mode="lines+markers", name=venue)
    style_fig(fig, height=300)
    fig.update_layout(yaxis_title="$")
    st.plotly_chart(fig, use_container_width=True)

with st.expander("Raw venue_cash rows for this date"):
    st.dataframe(view, use_container_width=True, hide_index=True)
