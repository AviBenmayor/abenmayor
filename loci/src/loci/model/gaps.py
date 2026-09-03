"""Present-day investment screen: conspicuous single-category gaps (per hex).

An area "ripe for investment" is one that is already walkable and lived-in but is
missing an OBVIOUS business — one that comparable walkable areas normally have, so
its absence stands out and genuinely hinders the area's walkability. That missing
business is the opportunity, today. No growth model; this is a cross-sectional
targeting screen.

Method: among populated hexes, measure each category's PREVALENCE (how often it's
present within a walk). A missing category counts as a conspicuous gap only if its
prevalence >= `expected` — i.e. areas like this normally have it. A hex qualifies
if it is otherwise walkable (>= `min_present` of 15 categories present) yet is
missing at least one expected business. The lead is the most-expected missing one.
"""
from __future__ import annotations

from loci.categories import CATEGORIES

ALLCATS = list(CATEGORIES)


def compute_gaps(con, threshold: int = 10, min_present: int = 12,
                 expected: float = 0.80, min_pop: float = 800.0):
    """Pure computation: returns (rows, prevalence) without writing. `expected` is the
    prevalence a category needs before its absence counts as a conspicuous gap; it
    is the screen's most sensitive knob (bank/hardware sit near 0.80–0.85), so sweep
    it with `loci gaps-sweep` before trusting a top-N list."""
    rows = con.execute("""
        SELECT h.h3_index, dm.population, list(a.category) present
        FROM analysis.hex h
        JOIN analysis.hex_demographics dm ON dm.h3_index=h.h3_index AND dm.acs_year=2023
        JOIN (SELECT DISTINCT h3_index, category FROM analysis.hex_poi_distance
              WHERE network_m <= ? * 80.0) a ON a.h3_index=h.h3_index
        WHERE dm.population > ?
        GROUP BY 1,2
    """, [threshold, min_pop]).fetchall()

    present = [(h, pop, set(pr)) for h, pop, pr in rows]
    n = len(present) or 1
    prevalence = {c: sum(1 for _, _, pr in present if c in pr) / n for c in ALLCATS}

    out = []
    for h, pop, pr in present:
        if len(pr) < min_present:
            continue
        missing = [c for c in ALLCATS if c not in pr and prevalence[c] >= expected]
        if not missing:
            continue
        lead = max(missing, key=lambda c: prevalence[c])
        out.append((h, threshold, pop, len(pr), lead, prevalence[lead], ",".join(missing)))
    return out, prevalence


def build_gaps(con, threshold: int = 10, min_present: int = 12,
               expected: float = 0.80, min_pop: float = 800.0) -> int:
    out, prevalence = compute_gaps(con, threshold, min_present, expected, min_pop)
    con.execute("DELETE FROM analysis.hex_gaps WHERE threshold_min = ?", [threshold])
    import pandas as pd
    df = pd.DataFrame(out, columns=["h3_index", "threshold_min", "population",
                                    "present_count", "lead_missing", "lead_prevalence",
                                    "missing_expected"])
    con.register("_g", df)
    con.execute("INSERT INTO analysis.hex_gaps SELECT * FROM _g")
    con.unregister("_g")
    return len(df), prevalence
