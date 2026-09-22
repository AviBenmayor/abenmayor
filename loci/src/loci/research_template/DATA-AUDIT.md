# __RQ_ID__ — Data audit

Scaffolded __DATE__ by `loci research new`. Every input the question needs, whether it
is already in the warehouse or not. Every `missing`/`partial` row's Gap column names a
ticket id (`GTM-\d+`) defined in `src/loci/tickets.py` — `loci research check` fails on
any ticket id here that does not resolve.

| Pillar | Input | Source | Publisher | History | Grain | Status | Gap → ticket |
|---|---|---|---|---|---|---|---|
| TODO | TODO | TODO | TODO | TODO | TODO | missing | TODO (GTM-TODO) |

Status is one of `present`, `partial`, `missing`. A `present` row needs no Gap entry;
`partial`/`missing` rows must name the ticket id that closes the gap.
