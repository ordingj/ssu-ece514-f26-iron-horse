# InfluxDB checkpoint workflow

We retrieve approved sensor fields from the public InfluxDB readings API.
We freeze source pages before preparing features or constructing labels.
We use the same captured pages throughout an experiment.

## 1. Check the environment and live contract

Use the Python 3.14.0 environment and pinned packages in the [README](../README.md).
Run the contract check:

```sh
python -m iron_horse doctor
```

The check requests metadata and matric quality fields in a small historical
window. It saves no readings and starts no model fit. A successful response
must include valid identity, location, response-format, checksum, and unit flags.
It does not establish calibration or complete historical coverage.

On November 11 the live doctor check passes and quality-enabled requests return
HTTP 200. The [readiness record](influx-readiness.json) retains this observation
and the earlier service rejection.
There is no automatic fallback to values without quality provenance.

## 2. Capture an immutable source

After the capability check passes, run:

```sh
SNAPSHOT='runs/influx-source'
OUT='runs/influx-checkpoint'
python -W error -u -m iron_horse run \
  --snapshot "$SNAPSHOT" --output "$OUT" --stage download
```

We request 16 streams in fixed seven-day windows with at most three concurrent
requests. Every request includes `include_metadata=true`. Matric-potential
requests also include `include_quality=true` on every page.
Start is inclusive and stop is exclusive. The source spans January 1 through
August 31, 2026, in America/Los_Angeles, including daylight-saving time.

Each response page is saved as compressed JSON. Its receipt records the query,
retrieval time, and SHA-256. Pagination continues while `next_offset` is non-null,
even when a decoded page is empty. Completed pages are verified before reuse.
`snapshot.json` records the complete windows, cursor chains, and quality policy.

API reads across pages are not an atomic database snapshot. Retrieval times
remain explicit. A fresh download can include later changes to historical data.
Use the saved snapshot to reproduce a particular experiment.

## 3. Apply the source quality policy

The [source contract](../metadata/public_api_contract.json) fixes policy
`reported-kpa-v1`. It requires these matric fields:

| Field | Required interpretation |
| --- | --- |
| `potential_quality` | Accept `reported_kpa_calibration_not_validated`; exclude `unknown_first_field_units` |
| `response_format` | A recognized plain, historical, partial-frame, or complete-frame response |
| `checksum_status` | The status required for that response format |
| `temperature_quality` | A recognized completeness flag, retained as provenance |

Complete frames require `verified`. Partial frames require
`legacy_verified_crc_unavailable`. Historical v-terminated pairs retain
`unavailable`, and plain pairs retain `not_present`. These are explicit source
states, not calibration certificates. We do not reject a supported historical
format merely because it lacks a checksum in the retained source.

Unknown potential units are excluded before hourly aggregation and labeling.
The client also stops if the API returns a documented matric fault value
(-9999 or -9992), which the source decoder should omit.
We do not infer units from numeric magnitude. Missing, unknown, or inconsistent
quality flags stop processing. Conflicting values or provenance at one device,
measurement, and timestamp make that entire observation key unavailable.

Device names, aliases, blocks, and slopes establish routing. They are not
predictors. Returned location metadata describes the deployed inventory rather
than historical sensor movements. Raw packets and soil quality flags are not
available through this contract. Soil predictors use finite public scalar
readings with visible conflicts excluded. Physical calibration remains unverified.

A snapshot without the required matric provenance cannot be upgraded by guessing
flags. Capture a fresh snapshot under the current contract.

## 4. Prepare features and eligibility

```sh
python -W error -u -m iron_horse run \
  --snapshot "$SNAPSHOT" --output "$OUT" --stage prepare
```

Preparation creates no future labels. It saves the source, quality policy,
code, schema, and scientific-cache hashes. It uses 24 numeric predictor slots:
current potential; six-hour and 24-hour trends; separate same-block soil probe
readings; and trailing weather means and rainfall totals.

An example is one matric location at one clock hour. Current potential is the
median of accepted readings in `(t - 1 hour, t]`. Inputs require potential above
-500 kPa, four observed hourly medians in the last six hours, and 18 in the last 24.
Soil readings must be no more than one hour old. Optional predictor gaps use
fitting-set medians and missingness indicators. Future values are never imputed.

Training uses January–May, validation uses June, and testing uses July–August.
Every target window must end strictly before the next partition boundary.
The future label requires observations in at least 20 of 24 hourly bins and
no gap longer than two hours, including both window endpoints.
A positive label has at least one accepted potential at or below -500 kPa in
`(t, t + 24 hours]`. Coverage gates apply equally to both classes.

## 5. Fit, freeze, and score

```sh
python -W error -u -m iron_horse run \
  --snapshot "$SNAPSHOT" --output "$OUT" --stage develop
python -W error -u -m iron_horse run \
  --snapshot "$SNAPSHOT" --output "$OUT" --stage evaluate
```

Development fits candidate preprocessing only on training data and selects
settings on June F1. It refits the selected pipelines on eligible January–June
rows, then saves model hashes before test labels are constructed.
The candidate grid, 0.70 cutoff, -500 kPa threshold, and success rules stay fixed.

Evaluation verifies the frozen source and models, constructs test labels once,
and scores RF, logistic regression, drying trend, and always-defer on identical
eligible examples. `coverage.csv` records sequential exclusions. F1 does not
replace the required support of 20 positive and 20 negative sensor-days.

Use `--stage all` to execute capture, preparation, development, and evaluation
in order. Choose a new output directory for each experiment. A complete saved
snapshot works offline; later stages use the source path recorded at preparation.

## 6. Verify and inspect

```sh
python -W error -m iron_horse verify "$OUT"
python -m iron_horse summary --folder "$OUT"
python -m json.tool "$OUT/independent_api_verification.json"
```

The independent verifier reconstructs accepted potential arrays from page bytes.
It applies explicit unit provenance, checks all hourly medians and trends,
replays eligibility and future labels, and verifies both fitted models and scores.
It also checks source hashes, freeze ordering, and exclusion arithmetic.
The compatibility script `scripts/verify_api_checkpoint.py` calls the same verifier.

`summary` with no folder displays the independently verified November 11
quality-aligned result. It needs no network or scientific Python packages.
The [qualification report](influx-qualification.md) records the completed real run
and its explicit reuse of verified soil and weather API pages.

## Evidence and limits

Tests use synthetic fixtures and small recorded decoder examples. An offline
end-to-end synthetic test exercises all stages and independent verification.
It is not a vineyard measurement. The real November 11 qualification is
reported separately, including its source reuse and independent receipts.
No deployment is part of this repository task.

Earlier artifacts are indexed in [experiments](experiments.md). Their code and
source identities remain preserved rather than being relabeled as new results.
