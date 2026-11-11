# InfluxDB quality-enabled checkpoint qualification

Team Iron Horse | November 11, 2026

The public API now accepts quality-enabled requests. We completed the real
checkpoint pipeline with policy `reported-kpa-v1`, then independently verified
the source, hourly inputs, eligibility, fitted predictions, and scores.
The drying-trend baseline F1 is **0.379310 on 1,638 eligible test sensor-hours**.

## Source and acceptance

We fetched 127 fresh matric-potential pages with `include_metadata=true` and
`include_quality=true`. We reused 1,415 verified soil and weather API pages
from the frozen November 5 capture. Those auxiliary inputs stayed fixed while
we qualified matric decoding and unit provenance. No matric page was reused.
This is a controlled real-data qualification, not a claim that every stream
was downloaded again on November 11.

The complete snapshot has 1,542 pages and 13,303,928 returned readings.
The fresh matric pages contain 1,139,139 returned rows:

| Response format | Returned rows |
| --- | --- |
| Plain or signed SDI-12 pair | 947,708 |
| Historical v-terminated pair | 185,047 |
| Partial frame with verified legacy checksum | 6,371 |
| Complete frame with verified checksum and CRC | 13 |

All four supported formats appear in the live capture. We retain their explicit
checksum states. Historical responses without checksum bytes do not become
checksum-verified merely because their numeric fields are accepted.

After duplicate handling, the snapshot contains 1,128,651 distinct matric keys.
The client excludes **128,668 unknown-unit Cc keys** before aggregation or labeling.
It accepts 999,983 reported-kPa observations and finds zero conflicting matric keys.
Returned row counts include duplicates; observation-key counts do not.
No missing unit flags or physical readings were inferred.

The [cache reuse receipt](../results/influx-qualification-2026-11-11/cache_reuse.json)
and [source summary](../results/influx-qualification-2026-11-11/source_summary.json)
record the auxiliary source digest, retrieval times, page counts, and code hashes.
The complete source is an immutable local snapshot, not an atomic live database read.

## Fixed experiment

Training uses January–May, validation uses June, and testing uses July–August
2026 in America/Los_Angeles. The threshold remains -500 kPa, the horizon is
24 hours, and classifier scores at least 0.70 predict the positive class.
The registered candidate grid, tie rules, eligibility gates, bootstrap, and
support requirements remain fixed. We selected no settings using test labels.

We froze the fitted pipelines before constructing July–August labels.
All seven June candidate F1 scores are zero. The tie rules select RF depth 4
with minimum leaf size 30 and logistic C = 0.1.

| Partition | Scheduled | Eligible | Positive | Negative |
| --- | --- | --- | --- | --- |
| Training | 14,396 | 8,476 | 24 | 8,452 |
| Validation | 2,784 | 1,283 | 45 | 1,238 |
| Test | 5,856 | 1,638 | 211 | 1,427 |

## Test results

| Method | F1 | Precision | Recall | TN / FP / FN / TP |
| --- | --- | --- | --- | --- |
| Drying trend | 0.379310 | 0.394872 | 0.364929 | 1309 / 118 / 134 / 77 |
| Random forest | 0.000000 | 0.000000 | 0.000000 | 1427 / 0 / 211 / 0 |
| Logistic regression | 0.018779 | 1.000000 | 0.009479 | 1427 / 0 / 209 / 2 |
| Always defer | 0.000000 | 0.000000 | 0.000000 | 1427 / 0 / 211 / 0 |

The test has 15 positive sensor-days and 62 negative sensor-days.
The primary hypothesis remains **not evaluable**, because positive support
falls below the required 20 sensor-days. The source fix does not establish
sensor calibration, an irrigation benefit, or an untouched confirmation set.
These results remain exploratory.

## Eligibility arithmetic

The 62-day test calendar has four locations, giving 5,952 candidate sensor-hours.
The strict boundary rule removes the final 24 decision hours at each location,
leaving 5,856 scheduled hours. The sequential exclusions are:

1. Remove 889 hours with a missing current value or inadequate history. This leaves 4,967.
2. Remove 3,292 already-dry hours among those with adequate history. This leaves 1,675.
3. Remove 37 inputs with inadequate future coverage. This leaves 1,638 scored hours.

```text
5,856 - 889 - 3,292 - 37 = 1,638
F1 = 2 × 77 / (2 × 77 + 118 + 134) = 0.3793103448275862
```

| Block | Eligible test hours | Positive test hours |
| --- | --- | --- |
| P | 820 | 128 |
| Cc | 779 | 58 |
| B North | 39 | 25 |
| F | 0 | 0 |

Each label requires observations in at least 20 future hourly bins and no gap
longer than two hours, including both endpoints. The future window is
`(t, t + 24 hours]`. Both classes use the same future-coverage rule.
Input eligibility requires current potential strictly above -500 kPa and
adequate trailing history. Missing optional predictors do not remove a row.

## Independent verification

The [independent receipt](../results/influx-qualification-2026-11-11/independent_api_verification.json)
checks all 1,542 page hashes, reconstructs accepted potential arrays, and replays
23,324 hourly input rows, 23,036 nonpurged labels, and all 1,638 test predictions.
Both frozen classifiers reproduce their saved scores. Source hashes, freeze
ordering, and sequential coverage counts pass.

A separate post-scoring audit matches every accepted potential timestamp and
value, all 23,324 input rows and 33 columns, and all test identities, targets,
predictions, and model scores to the preserved reference. RF and logistic
score differences are exactly zero. The reference enters neither preparation
nor fitting. This check establishes processing parity for this controlled
snapshot. It does not establish physical calibration or parity for a later,
independently refreshed auxiliary dataset.

The [parity receipt](../results/influx-qualification-2026-11-11/reference_parity.json)
and [source comparison](../results/influx-qualification-2026-11-11/source_comparison.json)
retain that audit outside the workflow procedure.

## Commands

The qualification used the existing client, with no change to its quality rules:

```sh
python -m iron_horse doctor
python -W error -u -m iron_horse run \
  --snapshot runs/influx-source-2026-11-11 \
  --output runs/influx-checkpoint-2026-11-11 --stage all
python -W error -m iron_horse verify runs/influx-checkpoint-2026-11-11
python -m iron_horse summary
```

The snapshot was seeded with the verified auxiliary API pages described above.
Reproduction from that complete snapshot needs a fresh output directory.
Use `--stage prepare`, then `develop` and `evaluate`, to avoid another download.
The [current workflow](influx-workflow.md) explains each stage and the source contract.

The [fixed plan](influx-qualification-plan.md) precedes labeling and fitting.
Raw pages, prepared observations, fitted models, and row-level predictions remain
under ignored runs/. The repository contains only aggregate results and provenance.
We performed no deployment, submission, or push.
