import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from auth import login_gate
from model import load_position_model
from theme import card_title, hero_row, page_header, style_fig, tone

st.set_page_config(page_title="MAG Desk P&L", layout="wide", page_icon="📊")

login_gate()

pos = load_position_model()

# ---------------- sidebar filters ----------------
st.sidebar.markdown('<div class="mag-kicker">Filters</div>', unsafe_allow_html=True)
venues = sorted(pos["venue"].unique())
leagues = sorted(pos["league"].unique())
sel_venues = st.sidebar.multiselect("Venue", venues, default=venues)
sel_leagues = st.sidebar.multiselect("League", leagues, default=leagues)

view = pos[pos["venue"].isin(sel_venues) & pos["league"].isin(sel_leagues)]

# ---------------- header + hero ----------------
page_header(
    "Manhattan Athletic Group",
    "Desk P&L",
    "How is the desk doing? Total P&L, split into realized and unrealized, sliceable by venue and league.",
)

realized = view["realized_pnl"].sum()
unrealized = view["unrealized_pnl"].sum()
total = realized + unrealized
notional = view["mag_stake"].sum()
fill_count = len(view)
open_count = int((view["status"] == "OPEN").sum())
won = int((view["status"] == "WON").sum())
lost = int((view["status"] == "LOST").sum())
win_rate = won / (won + lost) * 100 if (won + lost) else float("nan")

hero_row(
    [
        {"label": "Total P&L (revenue)", "value": f"${total:,.0f}", "tone": "primary"},
        {"label": "Realized P&L", "value": f"${realized:,.0f}", "tone": tone(realized)},
        {"label": "Unrealized P&L (open book)", "value": f"${unrealized:,.0f}", "tone": tone(unrealized)},
    ]
)

# ---------------- secondary stat cards ----------------
c1, c2, c3, c4 = st.columns(4)
for col, label, value in [
    (c1, "Notional volume", f"${notional:,.0f}"),
    (c2, "Fill count", f"{fill_count:,}"),
    (c3, "Open positions", f"{open_count:,}"),
    (c4, "Win rate (WON / WON+LOST)", f"{win_rate:.0f}%" if fill_count else "—"),
]:
    with col:
        with st.container(border=True):
            st.metric(label, value)

st.write("")

# ---------------- breakdown cards ----------------
def pnl_bar(df: pd.DataFrame, dim: str) -> go.Figure:
    g = df.groupby(dim, as_index=False).agg(
        realized=("realized_pnl", "sum"), unrealized=("unrealized_pnl", "sum")
    )
    fig = go.Figure()
    fig.add_bar(name="Realized", x=g[dim], y=g["realized"])
    fig.add_bar(name="Unrealized", x=g[dim], y=g["unrealized"])
    fig.update_layout(barmode="relative")
    style_fig(fig)
    return fig


left, right = st.columns(2)
with left:
    with st.container(border=True):
        card_title("P&L by venue")
        st.plotly_chart(pnl_bar(view, "venue"), use_container_width=True)

with right:
    with st.container(border=True):
        card_title("P&L by league")
        st.plotly_chart(pnl_bar(view, "league"), use_container_width=True)

with st.container(border=True):
    card_title(
        "Realized P&L trend",
        "Cumulative realized P&L by fill date. There's no settlement-date field in the "
        "data, so this uses filled_at as a proxy for when a trade entered the book — "
        "not the date it actually settled.",
    )
    settled = view[view["realized_pnl"].notna()].sort_values("filled_at").copy()
    settled["date"] = settled["filled_at"].dt.date
    daily = settled.groupby("date", as_index=False)["realized_pnl"].sum()
    daily["cumulative"] = daily["realized_pnl"].cumsum()
    if not daily.empty:
        fig = go.Figure()
        fig.add_scatter(x=daily["date"], y=daily["cumulative"], mode="lines+markers", name="Cumulative realized P&L")
        style_fig(fig, height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No settled fills in the current filter.")

left2, right2 = st.columns(2)
with left2:
    with st.container(border=True):
        card_title("Venue × league breakdown")
        pivot = view.groupby(["venue", "league"], as_index=False).agg(
            realized=("realized_pnl", "sum"),
            unrealized=("unrealized_pnl", "sum"),
            notional=("mag_stake", "sum"),
            fills=("fill_id", "count"),
        )
        st.dataframe(pivot, use_container_width=True, hide_index=True)

with right2:
    with st.container(border=True):
        card_title("Open positions (unrealized detail)")
        open_view = view[view["status"] == "OPEN"][
            ["fill_id", "venue", "league", "outcome", "mag_side", "mag_stake", "current_mark", "mark_as_of", "unrealized_pnl"]
        ].sort_values("unrealized_pnl")
        st.dataframe(open_view, use_container_width=True, hide_index=True)
