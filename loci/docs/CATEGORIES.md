# Loci — the daily-needs bundle

**GENERATED — do not edit.** Rendered by `loci gen-categories` from [`src/loci/categories.py`](../src/loci/categories.py) (slugs, tiers, labels, tier weights) and [`src/loci/categories.yaml`](../src/loci/categories.yaml) (the NAICS 2022 anchor and the headline-demotion flag). `tests/test_category_registry.py` fails if this table drifts from either file.

## The daily-needs bundle

Seventeen categories in four weighted tiers. Tier weights are judgment calls, stated explicitly so a reader can disagree with them precisely.

| Tier | w | # | Category | NAICS 2022 | Headline |
|---|---|---|---|---|---|
| **T1 Necessities** | **0.40** | 1 | Grocery / supermarket | 445110 | yes |
|  |  | 2 | Bodega / convenience | 445131 | yes |
|  |  | 3 | Pharmacy | 456110 | yes |
|  |  | 4 | Laundromat / dry cleaner | 812310, 812320 | yes |
| **T2 Personal services** | **0.20** | 5 | Hair / barber | 812111, 812112 | no |
|  |  | 6 | Nail / beauty | 812113 | yes |
|  |  | 7 | Tailor / repair | 811430 | no |
| **T3 Food & gathering** | **0.25** | 8 | Restaurant | 722511, 722513 | yes |
|  |  | 9 | Cafe / bakery | 722515, 311811 | yes |
|  |  | 10 | Bar / pub | 722410 | yes |
| **T4 Civic & wellness** | **0.15** | 11 | Childcare | 624410 | yes |
|  |  | 12 | Clinic / urgent care | 621111, 621493 | no |
|  |  | 13 | Fitness | 713940 | yes |
|  |  | 14 | Bank branch | 522110 | yes |
|  |  | 15 | Hardware / home supply | 444140 | yes |
|  |  | 16 | Bathhouse / sauna | 812199 | no |
| **T3 Food & gathering** | **0.25** | 17 | Brewery / taproom | 312120 | no |

### Demoted from headline claims

**Demoted from headline claims** (owner ruling 2026-09-14, D30 precedent): a gap in this category can still lead nowhere near as often as it looks like it should be a coverage hole rather than a real gap. It keeps its row, ratio and place on the map — `model/recommend.non_headline_categories()` only blocks it from being the LEAD card. See CONTEXT.md §4.2.

- Hair / barber
- Tailor / repair
- Clinic / urgent care
- Bathhouse / sauna
- Brewery / taproom

### Pinned definitions

A `definition:` in categories.yaml is the inclusion rule a hand enumeration (ground truth, base rate) counts against. Verbatim.

- **Bathhouse / sauna** (`bathhouse_sauna`): public-admission bathing facility whose primary offer is heat/water bathing — bathhouse, sauna, steam room, banya, hammam, Korean spa/jjimjilbang, per-visit plunge/thermal pools. Excludes day spa / health spa (stay in nails_beauty pending the wide-slug ruling), nail/med/massage-only, hotel-guest-only spas, gym or residential-building saunas, and membership-only clubs (flag, do not count). Owner ruling 2026-09-17 (via GTM-199): "day spa out UNLESS bathing is the primary offer" — Juvenex, Great Jones Spa and Fountain of Youth count; MN+BK stock reads ~21.

  Ships as a **non-filtering signal** (owner ruling 2026-09-17, docs/CATEGORY-EXPANSION.md §4): `headline: false`, it can reorder or annotate a card and never gates one; its gaps are not opportunity claims.

