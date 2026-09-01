# Lead scoring — code

The engineering behind the submission. The memo, the score and the rep tool came with the
submission itself; this repo is the part worth reading as code.

**Not everything is here.** The data was provided under confidentiality, and the terms allow
describing the approach but not the data — so the scored output, the write-up and most of the
analysis scripts are excluded. That exclusion is wider than it looks: the analysis scripts
carry findings in their comments and console output, which is the same data in prose, so they
are held back too. `.gitignore` names every excluded file with its reason. What's here is the
engineering that stands on its own with none of your numbers embedded in it.

## Decisions you may want to push on

**One model, several surfaces.** The fitted scikit-learn pipeline is collapsed into a
per-value coefficient lookup in JSON. For a linear model on one-hot features that transform
is exact rather than approximate, so the browser tool, the batch scorer and the API all
evaluate identical arithmetic instead of three implementations that drift apart. The
container fits nothing and unpickles nothing — it scores from that JSON, which also means the
serving path is not version-coupled to the scikit-learn that produced it.

**The parity harness is the load-bearing test.** `src/test_parity.js` extracts the JavaScript
out of the built HTML tool, runs it in Node against the Python model's outputs, and fails on
any disagreement. It also throws fourteen malformed CSVs at the parser — empty files, BOMs,
CRLF, quoted commas, wrong delimiters, duplicate keys, out-of-range numbers — and scores
50,000 rows to check it doesn't hang. Removing a calibration layer late in the build took
agreement from ~1e-13 to exactly zero, because it removed a log/exp round trip.

**Assertions where drift would otherwise be silent.** The batch scorer fails if its own fit
disagrees with the exported model; tier assignment fails if one record's tier differs from
the submitted file. Both fired during development and caught real divergence in seconds —
including the case where two artifacts had quietly ended up on different feature sets.

**A model deliberately smaller than the best one measured.** Features were kept or dropped on
whether their effect survived into a period they weren't fitted on, not on whether they moved
AUC. The larger model scored better on AUC and identically at the operational cutoff, which
is the only place a ranking becomes a phone call.

**Deployment that can't leak by accident.** `.railwayignore` uses an allowlist, so putting a
file on the host is a deliberate named act rather than a default. It caught a build during
development — a bundle failed to copy precisely because it hadn't been named.

## Layout

```
src/scorer.py             pure-numpy scorer; serving needs only pandas + numpy
src/test_parity.js        cross-language parity + malformed-input suite
src/model_final.py        model comparison, out-of-time validation
src/model_select.py       feature ablation, target-equivalence tests
src/target_choice.py      whether the candidate targets rank differently at all
src/build_demo_bundle.py  narrows a dataset to what a demo needs, and nothing more
src/run_all.py            end-to-end rebuild
app/                      FastAPI dashboard — data layer, charts, scoring endpoint
Dockerfile                fits nothing, unpickles nothing
```

Python · scikit-learn · pandas · FastAPI · Jinja2 · Docker · Railway · vanilla JS
