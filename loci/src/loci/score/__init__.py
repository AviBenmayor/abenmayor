"""Walkable access scoring and the Daily Needs Completeness Index.

CITY-AGNOSTIC. No NYC column names, no NYC assumptions. Consumes the normalized
staging.poi schema and a walk graph; emits analysis.hex_access and
analysis.hex_dnci.

Two decisions carry this module:

1. Access is computed with ONE multi-source Dijkstra per category, seeded from
   every POI in that category at once -- not one isochrone per hex. 15 graph
   traversals instead of ~7,400. CONTEXT.md 4.3.

2. Categories combine by WEIGHTED GEOMETRIC MEAN, not arithmetic. An arithmetic
   mean lets a hex with fifty restaurants and no grocery, pharmacy or laundromat
   score well -- precisely the failure the thesis exists to detect. Only the
   geometric form punishes zeros. CONTEXT.md 4.4.
"""
