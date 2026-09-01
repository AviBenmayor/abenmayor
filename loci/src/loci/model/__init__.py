"""Supply model, residual extraction, and the panel growth test.

- Supply model: DNCI ~ density + income + transit + COMMERCIAL ZONING CAPACITY
  + borough FE. The zoning term is required: without it the underserved tail
  fills with park edges and industrial zones. CONTEXT.md 4.5.
- Moran's I on residuals is mandatory, not optional. If spatial autocorrelation
  is present (it will be), re-estimate with a spatial error/lag model and report
  both. OLS standard errors on gridded urban data are otherwise wrong.
- Growth test must ship with its pre-trend check, placebo outcome and MAUP
  sweep. A coefficient without those three is not a finding. CONTEXT.md 4.6.
"""
