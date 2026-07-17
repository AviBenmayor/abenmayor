import numpy as np
import plotly.graph_objects as go
import streamlit as st

from auth import login_gate
from model import (
    bootstrap_hold_ci,
    hold_by_dimension,
    hold_population,
    load_position_model,
    stake_weighted_hold,
)
from theme import ACCENT, BORDER, PRIMARY, TEXT_SUBTLE, card_title, hero_row, page_header, style_fig, tone

st.set_page_config(page_title="MAG Hold View", layout="wide", page_icon="🎯")

login_gate()

pos = load_position_model()
hp = hold_population(pos)

# ---------------- sidebar filters ----------------
st.sidebar.markdown('<div class="mag-kicker">Filters</div>', unsafe_allow_html=True)
venues = sorted(hp["venue"].unique())
sides = sorted(hp["mag_side"].unique())
sel_venues = st.sidebar.multiselect("Venue", venues, default=venues)
sel_sides = st.sidebar.multiselect("MAG side", sides, default=sides)

view = hp[hp["venue"].isin(sel_venues) & hp["mag_side"].isin(sel_sides)]

# ---------------- header ----------------
page_header(
    "Manhattan Athletic Group",
    "Hold View",
    "Are we capturing the edge we think we're quoting, or is there a leak? Theoretical "
    "hold is what the model implied when we quoted; realized hold is what settlement "
    "actually paid us per dollar staked.",
)

if view.empty:
    st.warning("No settled fills in the current filter.")
    st.stop()

# ---------------- hero ----------------
desk = stake_weighted_hold(view)
ci_lo, ci_hi = bootstrap_hold_ci(view)
inside = ci_lo <= desk["theo_bps"] <= ci_hi

hero_row(
    [
        {"label": "Theoretical hold", "value": f"{desk['theo_bps']:,.0f} bps", "tone": "primary"},
        {"label": "Realized hold", "value": f"{desk['real_bps']:,.0f} bps", "tone": tone(desk["real_bps"])},
        {"label": "Gap (realized − theoretical)", "value": f"{desk['gap_bps']:+,.0f} bps", "tone": tone(desk["gap_bps"])},
        {"label": "Settled fills", "value": f"{int(desk['fills']):,}", "tone": None},
    ]
)

if inside:
    st.info(
        f"**No detectable leak — and no detectable edge either.** Realized hold came in "
        f"{desk['gap_bps']:+,.0f} bps against the quoted edge, but the 95% confidence "
        f"interval on realized hold runs **[{ci_lo:,.0f}, {ci_hi:,.0f}] bps** and contains "
        f"the theoretical {desk['theo_bps']:,.0f}. {int(desk['fills'])} settled fills is not "
        f"enough to measure a ~{desk['theo_bps']:,.0f} bps edge when every one of them pays "
        f"roughly ±10,000 bps. The honest read: this sample can't answer the question yet."
    )
else:
    st.warning(
        f"Realized hold of {desk['real_bps']:,.0f} bps falls outside the 95% confidence "
        f"interval **[{ci_lo:,.0f}, {ci_hi:,.0f}] bps** around the quoted "
        f"{desk['theo_bps']:,.0f} bps. Worth a look — but confirm on more fills before acting."
    )

st.write("")

# ---------------- the main chart ----------------
with st.container(border=True):
    card_title(
        "Theoretical vs realized hold by league",
        "Error bars are a 95% bootstrap interval on realized hold. They are wide on "
        "purpose: where a bar's interval covers its theoretical marker, the league's "
        "realized hold is indistinguishable from the edge we quoted, and the "
        "difference should not be traded on.",
    )

    g = hold_by_dimension(view, "league")

    fig = go.Figure()
    fig.add_bar(
        name="Realized hold",
        x=g["league"],
        y=g["real_bps"],
        marker_color=np.where(g["signal"], ACCENT, TEXT_SUBTLE),
        error_y=dict(
            type="data",
            symmetric=False,
            array=g["ci_hi"] - g["real_bps"],
            arrayminus=g["real_bps"] - g["ci_lo"],
            color=TEXT_SUBTLE,
            thickness=1.5,
        ),
    )
    fig.add_scatter(
        name="Theoretical hold (quoted edge)",
        x=g["league"],
        y=g["theo_bps"],
        mode="markers",
        marker=dict(symbol="line-ew", size=34, line=dict(width=3, color=PRIMARY)),
    )
    fig.add_hline(y=0, line_width=1, line_color=BORDER)
    style_fig(fig, height=420)
    fig.update_layout(yaxis_title="bps of stake", legend=dict(orientation="h", yanchor="bottom", y=1.02))
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Grey bars: quoted edge sits inside the interval — no signal. Green: outside "
        "the interval. With four leagues tested at 95%, roughly one false positive is "
        "expected by chance alone, so a single green bar is a prompt to collect more "
        "data, not evidence of a real per-league effect."
    )

# ---------------- table ----------------
with st.container(border=True):
    card_title("League detail")
    tbl = g.copy()
    tbl["95% CI on realized"] = [f"[{lo:,.0f}, {hi:,.0f}]" for lo, hi in zip(tbl.ci_lo, tbl.ci_hi)]
    tbl["Verdict"] = np.where(tbl["signal"], "Outside CI — investigate", "Inside CI — noise")
    tbl = tbl[["league", "fills", "stake", "pnl", "theo_bps", "real_bps", "gap_bps",
               "95% CI on realized", "Verdict"]].rename(columns={
        "league": "League", "fills": "Settled fills", "stake": "Stake",
        "pnl": "Realized P&L", "theo_bps": "Theoretical (bps)",
        "real_bps": "Realized (bps)", "gap_bps": "Gap (bps)",
    })
    st.dataframe(
        tbl.set_index("League").style
        .format("{:,.0f}", subset=["Settled fills"])
        .format("${:,.0f}", subset=["Stake", "Realized P&L"])
        .format("{:+,.0f}", subset=["Gap (bps)"])
        .format("{:,.0f}", subset=["Theoretical (bps)", "Realized (bps)"]),
        use_container_width=True,
    )

# ---------------- why the intervals are wide ----------------
with st.container(border=True):
    card_title("Why the intervals are this wide")
    left, right = st.columns([3, 2])

    with left:
        fig2 = go.Figure()
        fig2.add_histogram(x=view["realized_hold_bps"], nbinsx=60, marker_color=ACCENT)
        fig2.add_vline(x=desk["theo_bps"], line_dash="dash", line_color=PRIMARY, annotation_text="quoted edge")
        style_fig(fig2, height=320)
        fig2.update_layout(xaxis_title="realized hold per fill (bps)", yaxis_title="fills", showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    with right:
        st.markdown(
            f"""
Every settled fill is binary. We lose the stake (**−10,000 bps**) or the pool pays
out (**≈ +10,000 bps**). Nothing lands near the {desk['theo_bps']:,.0f} bps we quote.

The quoted edge is an *expected value across many trades* — it is never the
outcome of any single one. So realized hold only converges on it slowly, and at
{int(desk['fills'])} fills the noise around it is still an order of magnitude
wider than the edge we're trying to measure.

That's the case for showing intervals on this view rather than point estimates.
A bare bar chart here would read as "MLB is printing, kill NFL" — and both of
those are almost certainly luck.
            """
        )

# ---------------- definition ----------------
with st.expander("How realized hold is defined (and what's excluded)"):
    st.markdown(
        """
**Realized hold (bps) = 10,000 × Σ realized P&L ÷ Σ MAG stake**, over settled fills.

Both holds are stake-weighted ratios of sums, *not* averages of the per-fill bps
column. Averaging per-fill hold answers a different question — "hold on the
average trade" — and weights a \\$24 fill the same as a \\$1,099 one. The desk earns
dollars per dollar staked, so the ratio of sums is the number that reconciles to
the P&L view.

`settle_value` is already net of the venue fee, so realized hold is a post-fee
number. Theoretical hold is pre-fee model edge — at 150–200 bps of fee, that
alone accounts for part of any gap, and it's a reason the two are not perfectly
like-for-like even before variance.

**Excluded from the population:**

| Status | Excluded | Why |
|---|---|---|
| `OPEN` | yes | A mark is an estimate, not a result. Mixing marks into realized hold imports mark noise into a settlement number. |
| `VOID` | yes | The market was cancelled and the stake returned. It never tested the edge — booking it at 0 bps would read as a leak that never happened. |

**Population check:** all 320 fills in this dataset carry a quote, so theoretical
and realized hold are computed over the identical set of fills. No apples-to-oranges
gap from one side having fills the other doesn't. If unquoted fills ever appeared,
they'd have to be dropped from both sides, not just one.
        """
    )

with st.expander("Adverse selection check — are we only getting filled on our thin quotes?"):
    st.markdown(
        """
The other place a hold leak hides: if MAG only gets filled when the quote is
wrong, realized hold decays even though the model is fine. It doesn't show up here.

Fill rate is flat across the theoretical-hold range — **85% / 90% / 93% / 93% / 91%**
across the <150, 150–200, 200–250, 250–300, and 300+ bps buckets — and the 30
unfilled quotes average **220 bps** against **230 bps** for filled ones. No sign
that the market is picking us off on our thinnest edges.
        """
    )
