"""Shared visual system for the dashboard. Palette and type pulled from
novig.com/careers (Webflow site, colors read from its shipped CSS custom
properties: --_colors---primary--*, --_colors---accent--*,
--_colors---neutrals--*; fonts from its WebFont.load call: DM Sans, Inter,
Source Code Pro)."""

import streamlit as st

BG = "#0a0a14"
SURFACE = "#12121f"
ELEVATED = "#1a1a2e"
BORDER = "#2a2a40"

PRIMARY = "#28b1ff"
PRIMARY_LIGHT = "#90d6ff"
PRIMARY_DARK = "#4a6cd4"

ACCENT = "#24bf6c"
ACCENT_DARK = "#a8e063"

TEXT = "#f5f5fa"
TEXT_MUTED = "#a0a0b0"
TEXT_SUBTLE = "#9090a0"

GREEN = "#22c55e"
RED = "#ef4444"
YELLOW = "#f59e0b"
BLUE = "#64a7ff"

COLORWAY = [PRIMARY, ACCENT, PRIMARY_LIGHT, YELLOW, RED, BLUE]


def tone(value: float) -> str:
    if value is None:
        return ""
    try:
        if value > 0:
            return "pos"
        if value < 0:
            return "neg"
    except TypeError:
        pass
    return ""


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Inter:wght@400;500;600&family=Source+Code+Pro:wght@500;600;700&display=swap');

        html, body, [class*="css"], .stMarkdown, p, span, div {{
            font-family: 'DM Sans', 'Inter', sans-serif;
        }}

        [data-testid="stAppHeader"] {{ background: transparent; }}
        [data-testid="stAppDeployButton"] {{ display: none; }}
        footer {{ visibility: hidden; }}

        [data-testid="stSidebar"] {{
            background: {SURFACE};
            border-right: 1px solid {BORDER};
        }}
        [data-testid="stSidebar"] .mag-kicker {{ margin-top: .25rem; }}

        h1, h2, h3 {{ font-family: 'DM Sans', sans-serif; letter-spacing: -0.01em; }}

        /* card containers */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 14px;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] > div {{
            border-radius: 14px;
        }}

        /* metric widgets, used for secondary stat cards */
        [data-testid="stMetricValue"] {{
            font-family: 'Source Code Pro', monospace;
            font-weight: 600;
            color: {TEXT};
        }}
        [data-testid="stMetricLabel"] {{
            color: {TEXT_MUTED};
            text-transform: uppercase;
            letter-spacing: .06em;
            font-size: .72rem;
        }}

        /* alerts (verdict callouts) */
        [data-testid="stAlert"] {{
            background: {ELEVATED};
            border: 1px solid {BORDER};
            border-radius: 12px;
        }}

        [data-testid="stDataFrame"] {{
            border: 1px solid {BORDER};
            border-radius: 10px;
            overflow: hidden;
        }}

        .mag-kicker {{
            font-family: 'Inter', sans-serif;
            font-size: .7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: .14em;
            color: {PRIMARY_LIGHT};
            margin-bottom: .15rem;
        }}

        /* hero row */
        .mag-hero {{
            display: flex;
            flex-wrap: nowrap;
            overflow-x: auto;
            gap: 2.75rem;
            padding: .5rem 0 1.75rem 0;
            border-bottom: 1px solid {BORDER};
            margin-bottom: 1.75rem;
        }}
        .mag-hero-stat {{ flex: 1 0 auto; min-width: 150px; }}
        .mag-hero-label {{
            font-family: 'Inter', sans-serif;
            font-size: .72rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: .08em;
            color: {TEXT_MUTED};
            margin-bottom: .35rem;
            white-space: nowrap;
        }}
        .mag-hero-value {{
            font-family: 'Source Code Pro', monospace;
            font-weight: 600;
            font-size: clamp(1.4rem, 2.6vw, 2.3rem);
            line-height: 1.1;
            color: {TEXT};
            white-space: nowrap;
        }}
        .mag-hero-value.pos {{ color: {GREEN}; }}
        .mag-hero-value.neg {{ color: {RED}; }}
        .mag-hero-value.primary {{ color: {PRIMARY}; }}

        .mag-card-title {{
            font-family: 'DM Sans', sans-serif;
            font-weight: 600;
            font-size: .95rem;
            color: {TEXT};
            margin: .1rem 0 .6rem .1rem;
        }}
        .mag-card-caption {{
            font-family: 'Inter', sans-serif;
            font-size: .8rem;
            color: {TEXT_MUTED};
            margin: -.35rem 0 .75rem .1rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(kicker: str, title: str, caption: str) -> None:
    st.markdown(f'<div class="mag-kicker">{kicker}</div>', unsafe_allow_html=True)
    st.title(title)
    st.caption(caption)


def hero_row(stats: list[dict]) -> None:
    """stats: [{"label": str, "value": str, "tone": "pos"|"neg"|"primary"|None}]"""
    items = "".join(
        f'<div class="mag-hero-stat">'
        f'<div class="mag-hero-label">{s["label"]}</div>'
        f'<div class="mag-hero-value {s.get("tone") or ""}">{s["value"]}</div>'
        f"</div>"
        for s in stats
    )
    st.markdown(f'<div class="mag-hero">{items}</div>', unsafe_allow_html=True)


def card_title(text: str, caption: str | None = None) -> None:
    st.markdown(f'<div class="mag-card-title">{text}</div>', unsafe_allow_html=True)
    if caption:
        st.markdown(f'<div class="mag-card-caption">{caption}</div>', unsafe_allow_html=True)


def style_fig(fig, height: int = 360) -> None:
    fig.update_layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family="Inter, DM Sans, sans-serif", color=TEXT_MUTED, size=12),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT_MUTED)),
        colorway=COLORWAY,
        height=height,
        margin=dict(t=10, b=10, l=10, r=10),
    )
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER, color=TEXT_MUTED)
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER, color=TEXT_MUTED)
