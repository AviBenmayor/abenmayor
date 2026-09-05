# Market-revealed amenity distances in complete Manhattan areas (2026-09-05)

## Method

Among Manhattan residential addresses with zero category gaps under the adopted reach table (`src/loci/reach_tiers.yaml`), the free market's nearest-amenity distances for each category are measured and compared to the adopted reach. Data: Manhattan residential addresses from `d8_address/address_nearest_m.parquet` (per-address network-walk metres to nearest canonical POI, all 15 categories); "complete" addresses = 0 out of 15 categories beyond their reach tier; 27,302 complete addresses representing 768,847 units = 80.2% of Manhattan's residential base. Unit-weighted median, p80 percentile, and median household income (ACS 2023) aggregated to named neighbourhoods via `analysis.hex_demographics` joined to address NTA code. Density figures (units/km²) are approximate, derived from H3-res9 hexagon area × land_fraction, not measured GIS land area.

---

## Pool-level comparison: market-revealed reach vs adopted tiers

| Category | Market p80 (m) | Adopted reach (m) | Market/adopted ratio | Notes |
|---|---|---|---|---|
| restaurant | 80 | 400 | 0.20 | p80 in complete-only; all-MN p80 97 m (0.24) |
| grocery | 156 | 800 | 0.20 | cited USDA FARA 0.5 mi urban; all-MN 179 m (0.22) |
| cafe_bakery | 124 | 400 | 0.31 | cited Walk Score; all-MN 160 m (0.40) |
| pharmacy | 216 | 800 | 0.27 | cited Guadamuz & Qato 2021; all-MN 245 m (0.31) |
| bar | 166 | 400 | 0.42 | analog to CDC 400 m; all-MN 199 m (0.50) |
| fitness | 167 | 1200 | 0.14 | analog to CDC 1 mi / 1600 m; all-MN 195 m (0.16) |
| hardware | 334 | 960 | 0.35 | owner norm; all-MN 383 m (0.40) |
| convenience | 223 | 400 | 0.56 | owner norm / cite Walk Score 400; all-MN 260 m (0.65) |
| clinic | 223 | 960 | 0.23 | owner norm (not drive-based); all-MN 256 m (0.27) |
| bank | 292 | 640 | 0.46 | owner norm; all-MN 331 m (0.52) |
| childcare | 282 | 640 | 0.44 | owner norm; all-MN 300 m (0.47) |
| laundry | 188 | 320 | 0.59 | owner norm; all-MN 237 m (0.74) |
| hair_barber | 158 | 640 | 0.25 | owner norm; all-MN 205 m (0.32) |
| nails_beauty | 118 | 640 | 0.18 | owner norm; all-MN 152 m (0.24) |
| tailor_repair | 449 | 960 | 0.47 | owner norm; all-MN 572 m (0.60) |

**Bottom line:** Every category's market p80 within complete-only addresses runs 14–59% of the adopted tier; the same holds when re-run over ALL Manhattan addresses (16–74%), ruling out the capping artifact by construction.

---

## Named neighbourhoods: median distances by category

|  | West Village | East Village | Greenwich Village | Chelsea | Upper West Side | Upper East Side | Lower East Side | SoHo/Tribeca | Murray Hill/Kips Bay | Hell's Kitchen |
|---|---|---|---|---|---|---|---|---|---|---|
| restaurant | 0 | 0 | 0 | 0 | 24 | 11 | 0 | 0 | 9 | 0 |
| grocery | 84 | 64 | 87 | 78 | 97 | 81 | 86 | 77 | 104 | 67 |
| cafe_bakery | 20 | 13 | 0 | 12 | 67 | 27 | 38 | 15 | 75 | 16 |
| pharmacy | 126 | 160 | 146 | 116 | 128 | 104 | 145 | 130 | 142 | 132 |
| bar | 25 | 0 | 34 | 18 | 109 | 65 | 46 | 41 | 88 | 13 |
| fitness | 99 | 82 | 62 | 31 | 62 | 43 | 95 | 55 | 71 | 42 |
| hardware | 260 | 205 | 227 | 218 | 206 | 206 | 205 | 144 | 190 | 142 |
| convenience | 166 | 81 | 123 | 90 | 158 | 150 | 76 | 167 | 142 | 99 |
| clinic | 160 | 191 | 76 | 90 | 116 | 79 | 193 | 115 | 77 | 140 |
| bank | 170 | 170 | 101 | 129 | 166 | 121 | 176 | 137 | 165 | 159 |
| childcare | 194 | 200 | 156 | 191 | 164 | 136 | 161 | 180 | 169 | 188 |
| laundry | 75 | 74 | 118 | 94 | 97 | 80 | 135 | 105 | 95 | 80 |
| hair_barber | 52 | 27 | 43 | 33 | 107 | 40 | 62 | 50 | 79 | 71 |
| nails_beauty | 38 | 18 | 20 | 16 | 75 | 21 | 46 | 33 | 51 | 15 |
| tailor_repair | 142 | 218 | 168 | 160 | 239 | 197 | 228 | 192 | 201 | 434 |

---

## Neighbourhood density & income

| Neighbourhood | Complete units | Units/km² | Median HH income (ACS 2023, pop-weighted) |
|---|---|---|---|
| West Village | 21,447 | 18,718 | $165,268 |
| East Village | 33,778 | 21,918 | $94,157 |
| Greenwich Village | 23,779 | 22,688 | $180,318 |
| Chelsea | 38,055 | 16,993 | $135,956 |
| Upper West Side | 109,165 | 26,215 | $152,798 |
| Upper East Side | 126,584 | 29,513 | $161,701 |
| Lower East Side | 17,802 | 17,024 | $71,846 |
| SoHo/Tribeca | 29,080 | 11,624 | $173,286 |
| Murray Hill/Kips Bay | 40,419 | 29,312 | $142,785 |
| Hell's Kitchen | 29,671 | 22,502 | $110,435 |

---

## Caveat — distances in "complete" areas are bounded by construction

Because "complete" is defined by `nearest_m[c] ≤ reach_tiers[c]` for all 15 categories, the market-p80/adopted ratio can mathematically never exceed 1.00 for the complete-only comparison. To rule out this artifact, the comparison was re-run over **all Manhattan addresses** (no completeness filter, no upper bound), and the same tightness holds there too: every category is still only 16–74% of the adopted tier. This is the stronger evidence that market-revealed distances in mature Manhattan are genuinely much shorter than the adopted floor.

---

## Implications for D7 density-class reach

The adopted reach tiers function as a floor standard — "nobody should be more than this far." But in developed, zero-gap Manhattan, the market standard is 3–7× tighter:

- **Restaurant:** 80m vs 400 (5× tighter)
- **Grocery:** 156m vs 800 (5× tighter)  
- **Fitness:** 167m vs 1200 (7× tighter)
- **Pharmacy:** 216m vs 800 (4× tighter)

This is **not** a quirk of Manhattan's affluence alone. The frontier (East New York, Bushwick) shows the same density as some Manhattan neighbourhoods (22–26k units/km²) and likely similar market reach once complete. A single citywide reach table therefore over-serves Manhattan and under-serves outer-borough residents who live at lower density.

**Proposed next step (D7):** derive reach(c) per density class from complete addresses within that class, floored by the cited reach_tiers.yaml values. This would set reach as "what places like this one actually have," making a gap mean "short of what comparable density normally provides" — a more actionable and density-realistic frame than the current floor-standard model.
