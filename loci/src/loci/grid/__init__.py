"""H3 grid construction and dasymetric interpolation of ACS onto hexes.

- H3 res 9 (~0.105 km^2), shoreline-clipped, ~7,400 cells for NYC.
- ACS tracts -> hexes via tobler, dasymetric with PLUTO UnitsRes as the
  ancillary surface. Plain areal weighting would spread population across parks
  and rail yards.
- ACS margins of error are propagated, not dropped.

CONTEXT.md 2.3, 4.1, 4.2.
"""
