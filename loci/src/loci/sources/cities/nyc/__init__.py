"""NYC adapters: DOHMH, DCWP, NYS DOS, PLUTO, MTA, DOB/HPD.

These are the highest-quality data available for NYC and are deliberately not
portable. They exist behind the same adapter interface as universal sources so
that `loci/score/` never learns a NYC column name.

DOHMH (43nn-pn8j) is the anchor source: a near-census of food establishments,
used to calibrate the coverage undercount of biased sources. CONTEXT.md 7.1.
"""
