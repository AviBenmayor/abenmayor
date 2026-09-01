# Lead scoring and routing — a GTM engineering case study

A take-home exercise: paid inbound leads arrive faster than a sales floor can work them, so
which leads get attention is close to an accident. Build something that decides **who reps
should work, how hard, and how you'd know you were right.**

> **On the data.** The dataset was provided under confidentiality and is not in this repo.
> The exercise terms allow describing the approach, not the data, so the analysis scripts,
> the write-up and the scored output are all deliberately excluded — see `.gitignore`, which
> says which files are held back and why. What's here is the engineering that stands on its
> own without the client's numbers in it.

## The problem in one line

Roughly 4,000 leads a quarter arrive against a floor that can properly work about a third of
them. A ranking is only useful if it survives the moment a rep looks at it and decides
whether to believe it.

## Approach

**Predict expected value, then check whether the target even matters.** Three targets were
defensible — probability of winning, expected dollars, probability of winning this month. I
built all three and measured whether they actually rank differently. They didn't (Spearman
0.99+ between them), which turned "pick a target" from a modelling decision into a finding
worth reporting.

**Validate out-of-time, never on a random split.** The base rate drifted upward across the
training window and the acquisition mix shifted into the scoring window. A random split
trains on the future and reports a number that won't survive contact with production. Every
metric quoted came from training on the earlier months and scoring the later ones.

**Prefer the smaller model when the bigger one doesn't earn it.** Features were kept or
dropped on a *stability* test — does the effect hold up in a period it wasn't fitted on? —
not on whether they nudged AUC. Three fields beat six on that basis: the larger model scored
better on AUC but identically at the operational cutoff, which is the only place the ranking
turns into a phone call. Shipping the smaller one meant fewer things to defend and less to
break when the mix moves again.

**Choose the training population deliberately.** A third of the raw file was leads nobody
touched or that sat in broken owner buckets — none of which could have converted. Training
on them answers "what share of leads like this converted, including the ones nobody phoned,"
when the question a rep is actually holding is "if I call this, will it convert?" Restricting
to worked leads left the ranking untouched and fixed the probability level on its own, which
removed the need for a calibration layer entirely.

**Derive the operating constraint instead of assuming it.** Capacity wasn't provided. Rather
than inventing a number, it was reconstructed from the activity log — reps active per weekday
× touches per rep, against touches consumed per properly worked lead — and then stated as an
assumption with the direction of its likely error made explicit.

## Engineering

**One model, several surfaces.** A fitted scikit-learn pipeline is collapsed into a
per-value coefficient lookup in JSON. For a linear model on one-hot features that transform
is exact rather than approximate, which means the browser tool, the batch scorer and the
scoring API all evaluate the same arithmetic instead of three implementations that drift.

**The parity check is the point.** `src/test_parity.js` extracts the JavaScript from the
built HTML tool, runs it in Node against the Python model's outputs, and fails the build on
any disagreement. It also throws fourteen malformed CSVs at the parser — empty files, BOMs,
CRLF, quoted commas, wrong delimiters, duplicate keys, out-of-range numbers — and scores
50,000 rows to check it doesn't hang. Removing a calibration step later took that agreement
from ~1e-13 to exactly zero, because it eliminated a log/exp round trip.

**Assertions where drift would be silent.** The batch scorer fails loudly if its own fit
disagrees with the exported model, and tier assignment fails if a single record's tier
differs from the submitted file. Both fired during development and caught real divergence
within seconds.

**Offline-first for the demo.** The rep-facing tool is a single self-contained HTML file
that scores entirely in the browser. It's also served from the deployed app for convenience,
but it needs no server, no install and no network — a conference-room wifi problem shouldn't
be able to break a live demo.

## Layout

```
src/scorer.py            pure-numpy scorer; the serving path needs only pandas + numpy
src/test_parity.js       cross-language parity + malformed-input suite
src/model_final.py       model comparison and out-of-time validation
src/model_select.py      feature ablation and target-equivalence tests
src/target_choice.py     do the candidate targets actually rank differently?
src/build_demo_bundle.py narrows a dataset to what a demo needs, and nothing more
app/                     FastAPI dashboard — data layer, charts, scoring endpoint
Dockerfile               fits nothing and unpickles nothing; scores from exported JSON
```

Files carrying client-specific findings are excluded; `.gitignore` lists them individually
with the reason.

## Stack

Python · scikit-learn · pandas · FastAPI · Jinja2 · Docker · Railway · vanilla JS
