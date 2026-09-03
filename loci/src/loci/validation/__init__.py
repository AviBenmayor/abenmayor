"""Coverage validation (prediction P3, CONTEXT.md §7.1).

Google Places is used here as a SAMPLED ground truth, never as a data source:
Maps Platform terms forbid storing Places content, so the only thing written to
the database is a count per hex per category. The client enforces a hard call
budget in code (`LOCI_GOOGLE_CALL_BUDGET`) with a persisted counter.
"""
