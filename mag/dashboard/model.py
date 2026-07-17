"""Part 1 unified position model, ported from pos_model.q to pandas."""

import numpy as np
import pandas as pd


def load_position_model(data_dir: str = "data") -> pd.DataFrame:
    fills = pd.read_csv(f"{data_dir}/fills.csv", parse_dates=["filled_at"])
    marks = pd.read_csv(f"{data_dir}/marks.csv", parse_dates=["as_of"])
    quotes = pd.read_csv(f"{data_dir}/quotes.csv")

    # latest mark per fill_id: sort by date, take last per fill
    marks_sorted = marks.sort_values("as_of")
    lm = (
        marks_sorted.groupby("fill_id")
        .agg(current_mark=("mark_value", "last"), mark_as_of=("as_of", "last"))
        .reset_index()
    )

    # quotes keyed on fill_id, unfilled quotes dropped
    qk = quotes.dropna(subset=["fill_id"])[["fill_id", "theoretical_hold_bps"]]

    # unified position model: fills is the spine, qk/lm join on
    pos = fills.merge(qk, on="fill_id", how="left").merge(lm, on="fill_id", how="left")

    terminal = pos["status"].isin(["WON", "LOST", "VOID"])
    open_ = pos["status"] == "OPEN"
    settled = pos["status"].isin(["WON", "LOST"])

    pos["realized_pnl"] = (pos["settle_value"] - pos["mag_stake"]).where(terminal)
    pos["unrealized_pnl"] = (pos["current_mark"] - pos["mag_stake"]).where(open_)
    pos["realized_hold_bps"] = (
        1e4 * pos["realized_pnl"] / pos["mag_stake"]
    ).where(settled)

    return pos


def hold_population(pos: pd.DataFrame) -> pd.DataFrame:
    """Part 3 population: fills where theoretical and realized hold are both defined.

    WON/LOST only. OPEN has no realized number (a mark is an estimate, not a
    result) and VOID never tested the edge — the market was cancelled and the
    stake returned, so 0 bps would read as a leak that never happened.
    """
    return pos[pos["status"].isin(["WON", "LOST"]) & pos["theoretical_hold_bps"].notna()]


def stake_weighted_hold(d: pd.DataFrame) -> pd.Series:
    """Hold in bps, weighted by stake, over a set of settled fills.

    Both sides are pool-level ratios (total dollars / total dollars staked), not
    averages of the per-fill bps column. Per-fill realized hold is bimodal —
    roughly -10,000 bps on a loss, +10,000 on a win — so its mean answers "hold
    on the average trade," weighting a $24 fill the same as a $1,099 one. The
    desk earns dollars per dollar staked, so the ratio of sums is the number
    that ties back to P&L.
    """
    stake = d["mag_stake"].sum()
    if not stake:
        return pd.Series({"fills": len(d), "stake": 0.0, "pnl": 0.0,
                          "theo_bps": np.nan, "real_bps": np.nan, "gap_bps": np.nan})
    theo = (d["theoretical_hold_bps"] * d["mag_stake"]).sum() / stake
    real = 1e4 * d["realized_pnl"].sum() / stake
    return pd.Series({
        "fills": float(len(d)),
        "stake": stake,
        "pnl": d["realized_pnl"].sum(),
        "theo_bps": theo,
        "real_bps": real,
        "gap_bps": real - theo,
    })


def bootstrap_hold_ci(d: pd.DataFrame, n: int = 20_000, seed: int = 7,
                      alpha: float = 0.05) -> tuple[float, float]:
    """Percentile CI on stake-weighted realized hold, resampling fills.

    Resamples whole fills so the stake and the P&L move together, which keeps the
    ratio's denominator random the way it really is. Non-parametric on purpose:
    the per-fill payoff is two spikes, nowhere near normal, so a t-interval on
    the bps column would understate the spread.
    """
    if d.empty or not d["mag_stake"].sum():
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), (n, len(d)))
    pnl = d["realized_pnl"].values[idx].sum(axis=1)
    stake = d["mag_stake"].values[idx].sum(axis=1)
    draws = 1e4 * pnl / stake
    return (float(np.percentile(draws, 100 * alpha / 2)),
            float(np.percentile(draws, 100 * (1 - alpha / 2))))


def hold_by_dimension(d: pd.DataFrame, dim: str) -> pd.DataFrame:
    """Stake-weighted theoretical vs realized hold per slice, with a CI on realized
    and a verdict on whether the quoted edge is even distinguishable from noise."""
    rows = []
    for key, g in d.groupby(dim):
        row = stake_weighted_hold(g)
        row[dim] = key
        row["ci_lo"], row["ci_hi"] = bootstrap_hold_ci(g)
        row["signal"] = not (row["ci_lo"] <= row["theo_bps"] <= row["ci_hi"])
        rows.append(row)
    out = pd.DataFrame(rows)
    return out[[dim, "fills", "stake", "pnl", "theo_bps", "real_bps", "gap_bps",
                "ci_lo", "ci_hi", "signal"]].sort_values("stake", ascending=False)


def load_venue_cash(data_dir: str = "data") -> pd.DataFrame:
    """Part 4 source data. Kept separate from the position model — venue_cash is
    keyed on (venue, as_of), a different grain (capital at an exchange on a given
    day) with no fill_id to join through."""
    vc = pd.read_csv(f"{data_dir}/venue_cash.csv", parse_dates=["as_of"])
    vc["total_capital"] = vc["posted_collateral"] + vc["free_cash"]
    return vc
