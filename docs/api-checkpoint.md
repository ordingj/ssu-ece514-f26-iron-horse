# ECE514 checkpoint pipeline using the InfluxDB API

Team Iron Horse | November 5, 2026

We changed from the original CSV workflow to the public InfluxDB API. This guide explains how we retrieve sensor readings, prepare hourly inputs, fit and evaluate the models, and verify the results. Our drying-trend baseline F1 is 0.379310 on 1,381 eligible test sensor-hours.

This page records the November 5 API snapshot and implementation.
Use the [current API workflow](influx-workflow.md) for new quality-aligned runs.
Reproduce this recorded procedure with its [pinned implementation](legacy-reproduction.md).

## 1. Scope and source contract

We use January–May for training, June for validation, and July–August for testing. Calendar boundaries follow America/Los_Angeles, including daylight-saving time. September readings are outside the study period. The target is an accepted potential at or below -500 kPa within the next 24 hours. The classifier cutoff is 0.70.

The API returns numeric readings with stable sensor aliases. We request device metadata with `include_metadata=true`.
The returned device names, DevEUIs, blocks, and slopes identify our four matched locations and auxiliary probes.
Device identifiers, coordinates, and labels are not model predictors.
The metadata describes the inventory deployed with the API, rather than historical sensor movements.

Our captured device inventory routes matric sensors as follows:

| Matric device | Block | Terrain | Matched soil-water device |
| --- | --- | --- | --- |
| SDI-12-LS-US915-1 | P | upslope | SE01-LS-2 |
| SDI-12-LS-US915-2 | Cc | downslope | SE01-LS-1 |
| SDI-12-LS-US915-4 | B North | upslope | SE01-LS-3 |
| SDI-12-LS-US915-5 | F | upslope | SE01-LS-4 |

Each location uses its matched soil-water probe, same-block auxiliary probes, and the block I weather station. We retain separate terrain positions and probe numbers.

The public API returns decoded numeric readings. The following limits apply when interpreting those readings:

- The matric decoder accepts supported two-number and signed SDI-12 responses. Unsupported response formats are omitted.
- Raw response tokens are unavailable. Potential units follow the public measurement contract. Early Cc field units cannot be independently verified from numeric responses alone.
- Soil quality flags and raw-packet conflicts are unavailable.
- Numeric conflicts visible in the API remain excluded at the device, measurement, and timestamp key.

## 2. Project and environment

Our standalone package is under local review. Its project files have not been pushed to the group remote. Run these commands from the project directory. The initial download requires an internet connection; the public endpoint requires no account or token.

```sh
uv venv --python 3.14.0 .venv
uv pip install --python .venv/bin/python -r requirements.lock.txt
source .venv/bin/activate
python -W error -m unittest discover -s tests -p 'test_*.py'
```

The lock file fixes scikit-learn at 1.9.1. `-W error` makes Python warnings fail the check.
Our tests use synthetic windows and small decoder fixtures. The real API run is a separate measurement.

## 3. Request and freeze the source

A small metadata-enabled query demonstrates the public response:

```sh
curl --fail --get \
  'https://nrp-thingsboard-influxdb.nrp-nautilus.io/anonymous/v1/readings' \
  --data-urlencode 'measurement=matric_potential_kpa' \
  --data-urlencode 'include_metadata=true' \
  --data-urlencode 'start=2026-08-01T07:00:00Z' \
  --data-urlencode 'stop=2026-08-01T08:00:00Z' \
  --data-urlencode 'limit=100'
```

August 1 at 07:00 UTC is local midnight. `start` is inclusive and `stop` is exclusive.
The command returns one page, so it is a demonstration rather than the complete study download.

We download the 16 required streams in seven-day windows, using at most three concurrent requests.
The streams comprise potential, five weather fields, and ten soil-water and soil-temperature fields.
Soil fields include the base channel and channels 1 through 4. We retain their separate device and probe identities.

```sh
SNAPSHOT='runs/api-source-2026-11-05'
OUT='runs/api-checkpoint-2026-11-05'
python -W error -u -m iron_horse.api_checkpoint \
  --snapshot "$SNAPSHOT" --output "$OUT" --stage download
```

The client requests 10,000 source rows per page and follows every non-null `next_offset`.
An empty decoded page can still have another page. We never stop merely because `readings` is empty.
Each response keeps its original JSON numbers and timestamps in a compressed page file.
A receipt records the query, retrieval time, row count, and compressed-file SHA-256.
Completed pages can resume after an interruption only if their receipts and hashes match.

`snapshot.json` is written only after all windows and cursor chains finish.
It records January 1 at 08:00 UTC through September 1 at 07:00 UTC, with the latter excluded.
The API reads are not an atomic database snapshot. Later replication could change a fresh download.
The saved pages define the exact source for this run and all offline reruns from this snapshot.

## 4. Prepare observed inputs

```sh
python -W error -u -m iron_horse.api_checkpoint \
  --snapshot "$SNAPSHOT" --output "$OUT" --stage prepare
```

Preparation checks all source-page hashes, windows, cursors, and returned metadata.
It retains the required devices and collapses identical numeric keys.
Conflicting numeric values at one device, measurement, and timestamp become unavailable.
Missing readings remain missing. We add no interpolation, clipping, irrigation labels, or reconstructed packet digits.

Potential arrays keep actual observation times for future-gap checks.
Hourly potential uses the median of accepted observations in `(t - 1 hour, t]`.
The six-hour and 24-hour trends fit a straight line to observed hourly medians using elapsed hours.

We construct 24 numeric predictor slots:

| Predictor | Time rule |
| --- | --- |
| Current potential | Current right-closed hourly median |
| Six-hour and 24-hour trends | Trailing hourly medians, including the current bin |
| Soil water and temperature | Latest same-block probe value no more than one hour old |
| Air temperature, humidity, solar radiation, wind | Means of observations in the preceding 24 hours |
| Rainfall | Sum of distinct accepted interval amounts in the preceding 24 hours |

Soil slots retain terrain position and probe number. Multiple devices in a slot use their median.
Identifiers and coordinates do not enter the numeric slots.
Optional predictor gaps do not remove a row whose potential and target satisfy eligibility.

Preparation saves the source digest, code hashes, schema hash, and cache hashes before constructing labels.

## 5. Apply eligibility and purge partition boundaries

A scheduled example is one location at one clock hour, before checking data coverage.
There are 62 July–August days and four locations: `62 × 24 × 4 = 5,952` candidate sensor-hours.
We retain a time only when its 24-hour future window ends strictly before the next partition boundary:

```python
retain = t + pd.Timedelta(hours=24) < next_boundary
```

For testing, the boundary is September 1 at local midnight.
August 30 at 23:00 remains. August 31 at 00:00 does not, because its target ends exactly at the boundary.
All 24 August 31 decision hours are excluded at each location.
This removes 96 examples and leaves **5,856 scheduled test sensor-hours**.
The same strict comparison removes the final 24 decision hours of training and validation.

Each remaining example passes four gates:

1. The current hourly potential median exists and is strictly above -500 kPa.
2. At least four of the last six hourly medians and 18 of the last 24 exist.
3. Future readings occupy at least 20 of the next 24 bins, with no gap longer than two hours.
4. The target window ends strictly before the partition boundary.

The future interval is `(t, t + 24 hours]`. Its gap calculation includes both endpoints.
Both positive and negative labels require the same future coverage.
A positive label means at least one accepted future reading is at or below -500 kPa.
We never impute a future value.

`coverage.csv` counts sequential exclusions without overlap: missing current/history, already dry, missing future coverage, then eligible.
Its measured arithmetic and per-location counts appear in the results section.
Future coverage controls whether a prediction can be scored afterward. It never supplies a predictor at issue time.

The separate support rule requires at least 20 positive and 20 negative sensor-days.
A sensor-day is a location and local date, not an independent drying episode.
One mixed day can count toward both classes. This support check does not remove individual eligible hours.

## 6. Fit, select, and freeze the models

```sh
python -W error -u -m iron_horse.api_checkpoint \
  --snapshot "$SNAPSHOT" --output "$OUT" --stage develop
```

We fit preprocessing on training rows only for each candidate.
We remove entirely missing and constant numeric columns, fill retained gaps with fitting-set medians, and append missingness indicators.
RF keeps numeric predictors unscaled. Logistic regression uses fitting-set means and population standard deviations.
No class weighting, rebalancing, calibration, or outcome-driven feature selection is added.

RF uses 300 bootstrap trees, Gini splits, square-root feature sampling, and seed 514. It compares depths 4 and 8 with minimum leaf sizes 10 and 30. Logistic regression uses L2 regularization with C values 0.1, 1, and 10, lbfgs, tolerance 0.0001, and 1,000 iterations.

```python
prediction = positive_class_score >= 0.70
```

We select the highest June F1. Tied forests favor shallower trees, then larger leaves.
Tied logistic models favor smaller C. We refit both selected pipelines on eligible January–June rows.
`model_freeze.json` records settings, code hashes, schema hash, and model hashes before test labels exist.
A model score is not a calibrated probability of irrigation need.

## 7. Open the test and calculate the baseline

```sh
python -W error -u -m iron_horse.api_checkpoint \
  --snapshot "$SNAPSHOT" --output "$OUT" --stage evaluate
python -m iron_horse summary --folder "$OUT"
```

Evaluation verifies the frozen inputs and models before writing `test_unlock.json`.
It then constructs July–August labels once and scores every method on the same eligible rows.

```python
baseline_prediction = (
    (trend_6h_kpa_per_h < 0)
    & (current_potential_kpa + 24 * trend_6h_kpa_per_h <= -500)
)
F1 = 2 * TP / (2 * TP + FP + FN)
precision = TP / (TP + FP)
recall = TP / (TP + FN)
```

The baseline extrapolates the six-hour drying trend 24 hours ahead and has no fitted settings. Always-defer predicts zero. An undefined F1 is reported as zero. Success requires RF to improve F1 over the drying-trend baseline by at least 0.05 and achieve recall of at least 0.80. We calculate a descriptive paired interval with 2,000 seven-day bootstrap resamples and seed 514. Late-season data were inspected during project development, so this is an exploratory evaluation.

## 8. Independent verification and offline reruns

```sh
python -W error scripts/verify_api_checkpoint.py "$OUT"
python -m json.tool "$OUT/results.json"
python -m json.tool "$OUT/independent_api_verification.json"
```

The independent script hashes all pages and reconstructs potential arrays from the public responses without the adapter's cleaner.
It checks every hourly median, both trends, historical coverage, nonpurged future label, and eligibility decision.
It replays both fitted classifiers, baseline predictions, confusion counts, and F1.
It also checks freeze ordering and reconciles the coverage exclusions.
The verification receipt is written once in each completed run.

An offline rerun uses the same snapshot with a fresh output directory:

```sh
python -W error -u -m iron_horse.api_checkpoint \
  --snapshot "$SNAPSHOT" --output runs/api-checkpoint-offline-replay \
  --stage prepare
python -W error -u -m iron_horse.api_checkpoint \
  --output runs/api-checkpoint-offline-replay --stage develop
python -W error -u -m iron_horse.api_checkpoint \
  --output runs/api-checkpoint-offline-replay --stage evaluate
python -W error scripts/verify_api_checkpoint.py runs/api-checkpoint-offline-replay
```

Preparation reads only saved pages. Development and evaluation read the snapshot path recorded during preparation.
A fresh `--stage all` command combines download, preparation, development, and evaluation.
A completed snapshot is verified and reused, rather than silently refreshed.
Use a different snapshot directory to capture a new version of the service.

## 9. Measured results

We completed the end-to-end run from 1,542 public response pages containing 13,112,497 returned readings.
The compressed response files occupy 158,058,814 bytes, or about 158 MB.
The first source capture took about 43 minutes on this connection. Saved snapshots avoid that download on later runs.
The baseline F1 is **0.379310** on **1,381 eligible test sensor-hours**.

| Method | F1 | Precision | Recall | TN / FP / FN / TP |
| --- | --- | --- | --- | --- |
| Drying trend | 0.379310 | 0.394872 | 0.364929 | 1052 / 118 / 134 / 77 |
| Random forest | 0.000000 | 0.000000 | 0.000000 | 1170 / 0 / 211 / 0 |
| Logistic regression | 0.009434 | 1.000000 | 0.004739 | 1170 / 0 / 210 / 1 |
| Always defer | 0.000000 | 0.000000 | 0.000000 | 1170 / 0 / 211 / 0 |

The baseline has 77 true positives, 118 false positives, and 134 false negatives:

```text
F1 = 2 × 77 / (2 × 77 + 118 + 134) = 0.3793103448275862
```

| Partition | Scheduled | Eligible | Positive | Negative |
| --- | --- | --- | --- | --- |
| train | 14,396 | 6,236 | 24 | 6,212 |
| validation | 2,784 | 1,283 | 45 | 1,238 |
| test | 5,856 | 1,381 | 211 | 1,170 |

All seven June candidate F1 scores are zero.
The fixed tie rules select RF depth 4 with minimum leaf size 30 and logistic C = 0.1.
The API training set contains 24 positive hours among 6,236 eligible hours, or about 0.385 percent.
The final refit uses 7,519 eligible January–June hours, including 69 positives.
These hours remain correlated forecast opportunities rather than independent events.

RF predicts no positive test hours because its highest positive-class score is 0.425186, below the fixed 0.70 cutoff. Logistic regression predicts one true-positive hour and has F1 of 0.009434. The score cutoff is fixed for all candidate and final models.

### Measured eligibility arithmetic

The scheduled test grid contains 5,856 hours. Sequential exclusions are:

1. Exclude 1,089 hours with a missing current value or inadequate history. This leaves 4,767.
2. Exclude 3,292 already-dry hours among those with sufficient history. This leaves 1,475 advance-warning inputs.
3. Exclude 94 inputs without adequate future coverage. This leaves 1,381 scored hours.

```text
5,856 - 1,089 - 3,292 - 94 = 1,381
```

| Block | Eligible test hours | Positive test hours |
| --- | --- | --- |
| P | 563 | 128 |
| Cc | 779 | 58 |
| B North | 39 | 25 |
| F | 0 | 0 |

The test has 15 positive sensor-days and 54 negative sensor-days.
The positive count remains below the required 20, so the registered primary hypothesis remains **not evaluable**.
RF also fails both numerical success thresholds.
The descriptive paired interval for RF minus baseline F1 is [-0.489187, -0.080556].

### Verification results

The independent replay verified all 1,542 page hashes, 23,324 hourly input rows, 23,036 nonpurged labels, and 1,381 test predictions.
Both frozen classifiers reproduce their saved scores. All coverage exclusions reconcile.
Our complete group suite passes 97 tests with warnings treated as errors.

## 10. Saved outputs and interpretation

| Artifact | Purpose |
| --- | --- |
| Source `pages/*.json.gz` and receipts | Original public response bytes, query, retrieval time, and page digest |
| Source `snapshot.json` | Complete window and pagination manifest |
| `preparation.json` | Source, adapter, environment, schema, and cache digests |
| `cleaning_audit.json` | Visible conflicts and unavailable raw checks |
| `decode_audit.json` | Public potential counts by device |
| `feature_schema.json` | Ordered 24-slot predictor schema |
| `development.json` | Class counts, seven validation trials, and selected settings |
| `model_freeze.json`, `test_unlock.json` | Model freeze and test-opening records |
| `coverage.csv`, `results.json` | Eligibility, metrics, support, and hypothesis status |
| `test_predictions.csv` | Local row-level predictions |
| `independent_api_verification.json` | Source, timing, label, prediction, and scoring replay evidence |

Response pages, fitted models, and row-level outputs remain under ignored runs/. Only aggregate results and provenance enter the reviewable repository. We have not pushed project changes. This evaluation predicts observed sensor thresholds under existing vineyard management. It establishes neither sensor calibration nor an optimal irrigation action.

## Sources

- [Current preregistration](https://docs.google.com/document/d/1d3L8nC-RSejREsTm4iYgjuQil-4KQ5jSpYOVoJcekd0/edit)
- [Public measurement catalog](https://nrp-thingsboard-influxdb.nrp-nautilus.io/anonymous/v1/measurements)
