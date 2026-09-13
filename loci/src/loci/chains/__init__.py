"""Chain detection and tracking.

Two audiences, one list:

  * **sales** — retail/consumer brands opening aggressively in NYC are the
    companies a site-selection product is sold to;
  * **signal** — "brand X just opened two blocks away" is evidence about a
    location that no POI count carries. Nothing here consumes that yet; the
    `loci_category` join key on every brand is what will make it possible.

The package deliberately splits DETERMINISTIC from NARRATIVE:

  `detect`     open data only, reproducible, no network beyond the warehouse.
  `research`   press hits via Tavily — costs money, budgeted in code.
  `watchlist`  the human-maintained YAML that outranks both.
  `render`     docs/CHAINS.md, generated, never hand-edited.
"""
