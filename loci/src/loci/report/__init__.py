"""THE ON-DEMAND ALLOCATOR REPORT (D100, GTM-172, seed AC-16..AC-21).

`loci report <address>` turns one Loci address into a markdown memo a capital
allocator can act on: category call + falsification test, supply with
open/closed/unknown status, demand + catchment economics, and legality/rents/
risk/exit -- the four headings `render.HEADINGS` names. Every paid call
(Google Places, Tavily, Anthropic) is charged against a hard per-report cap
(default $1.00, `ledger.Budget`) BEFORE it is made, and a 30-day disk cache
(`cache.py`) keyed on the address and the evidence it saw makes a second run
for the same address free.

Module map (see /private/tmp/.../design-allocator-report.md for the full
design; RECONCILED with design-closure-evidence.md 2026-09-14):
    clients.py   Protocols for the three paid APIs + `default_clients()`.
    evidence.py  `EvidencePack` -- the read side: warehouse facts, grades,
                 forecast, supply-with-status, legality, demand, all in one
                 dataclass with a stable `hash()` for the cache key.
    enrich.py    The write/spend side: three Tavily searches (rents, leases,
                 news) plus on-demand closure checks for 'unknown' POIs in
                 the catchment, each preceded by a budget charge.
    prose.py     Exactly ONE Anthropic call against a fixed outline.
    render.py    Deterministic tables + prose -> the four-heading markdown.
    cache.py     30-day disk cache keyed on (address_id, evidence_hash).
    ledger.py    `Budget`/`CapExceeded` -- the spend-cap enforcement, shared
                 with `loci verify-closures` via `analysis.spend_ledger`
                 (sql/033).
    run.py       `generate()` -- wires all of the above; what the CLI (owned
                 by a peer session) and the webmap's async job both call.

ANTHROPIC_API_KEY is OPTIONAL. `clients.default_clients()` returns
`prose=None` when it is unset, and `render.render()` still fills all four
headings with their deterministic tables plus a "prose unavailable" line --
AC-16 (the four headings are non-empty) holds with no key configured.
"""
