# Lead scoring — the code

This is the engineering side of the submission. You already have the memo, the scored
file and the rep tool; this repo is for anyone who wants to see how the pieces were
actually built and why they're shaped the way they are.

## What's not here, and why

The data came with a confidentiality condition, and the terms let me talk about the
approach but not the data. I took that seriously, and it turned out to cut deeper than
just leaving out the CSVs. Most of my analysis scripts have the findings written into
their comments and print statements — channel performance, rep patterns, segment win
rates — and a script that says the number out loud is the number, whatever the file
extension. So those stayed out too.

Every excluded file is listed in `.gitignore` with a reason next to it. What survived is
the code that stands on its own without any of your numbers inside it.

One consequence worth saying up front: **this repo is for reading, not running.** The
scripts here import the feature definitions and the fitted model, and those files carry
findings in their comments, so they're held back. Clone it and the imports fail. That's the
cost of the exclusion, and I'd rather take it than sanitise the code into something that
runs but no longer says what I actually did.

## What I built, and the thinking behind it

**I collapsed the model into a lookup table so nothing could drift.** There were three
places that needed to score a lead — the browser tool, the batch scorer, and the API — and
the thing I was most worried about was those three quietly disagreeing. So rather than
ship the scikit-learn pipeline and reimplement it twice, I flattened the fitted model into
a per-value coefficient lookup in JSON. Because it's a linear model on one-hot features,
that's an exact transform, not an approximation. Every surface reads the same file and
does the same arithmetic. It also means the container never fits or unpickles anything;
it's not tied to the scikit-learn version that produced the model.

**Then I wrote a test that would tell me if that promise broke.** `src/test_parity.js`
pulls the JavaScript out of the built HTML tool, runs it in Node against the Python
model's outputs, and fails on any difference. While I was at it I made it throw fourteen
ugly CSVs at the parser — empty files, BOMs, CRLF endings, quoted commas, the wrong
delimiter, duplicate keys, out-of-range numbers — and score fifty thousand rows to make
sure it wouldn't hang in front of someone. When I removed a calibration layer late on, the parity gap went from around 1e-13 to
exactly zero — there was no longer a log/exp round trip for floating point to disagree
about.

**I put assertions where a mistake would otherwise be silent.** The batch scorer refuses
to run if its own fit doesn't match the exported model. Tier assignment refuses if even
one record's tier differs from the file being submitted. Both of these went off during
development — once because two artifacts had ended up on different feature sets without
me noticing — and each time they saved me from shipping something inconsistent.

**I shipped a smaller model than the best one I measured.** I decided which features to
keep by asking whether their effect held up in a period they hadn't been fitted on, not
by whether they nudged AUC. The bigger model won on AUC and tied at the operational
cutoff — and the cutoff is the only place where a ranking turns into a phone call. Fewer
fields meant fewer things to defend in front of a rep and less to break the next time
the acquisition mix moves.

**I made it hard to leak by accident.** `.railwayignore` is an allowlist, so getting a
file onto the host is a deliberate, named act rather than the default. It bit me once:
a build failed because a bundle I wanted to ship hadn't been added to the list. That's
the guardrail working, and I'd rather have that failure than the other kind.

## Where things are

```
src/scorer.py             pure-numpy scorer; serving needs only pandas + numpy
src/test_parity.js        cross-language parity, plus the malformed-input suite
src/model_final.py        model comparison and out-of-time validation
src/model_select.py       feature ablation and target-equivalence tests
src/target_choice.py      whether the candidate targets even rank differently
src/build_demo_bundle.py  cuts a dataset down to what a demo needs and nothing more
app/                      dashboard data layer, charts and scoring helpers (the routes
                          carry findings and are held back)
Dockerfile                fits nothing, unpickles nothing
```

Python · scikit-learn · pandas · FastAPI · Jinja2 · Docker · Railway · vanilla JS
