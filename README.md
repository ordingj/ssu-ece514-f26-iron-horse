# ECE514 Iron Horse vineyard forecasting

We are Team Iron Horse. We use the public InfluxDB API to forecast an observed
matric-potential threshold within 24 hours. We compare random forest, logistic
regression, and a six-hour drying-trend baseline. The threshold is -500 kPa.
This forecasts a sensor outcome under existing vineyard management.

## Current workflow

Start with the [InfluxDB workflow](docs/influx-workflow.md). It covers setup,
source quality, capture, preparation, model freeze, scoring, and verification.
The project needs no database account or local sensor export.

**Live source status:** on November 11, the public endpoint accepts quality-enabled
requests and the doctor check passes. The repository requires those quality fields
before accepting matric observations. The [readiness record](docs/influx-readiness.json)
retains the current check and the earlier service rejection.

Create the pinned environment from this directory:

```sh
uv venv --python 3.14.0 .venv
uv pip install --python .venv/bin/python -r requirements.lock.txt
source .venv/bin/activate
python -W error -m unittest discover -s tests -p 'test_*.py'
```

Check source support before starting a download:

```sh
python -m iron_horse doctor
```

After that check passes, choose separate snapshot and output directories:

```sh
python -W error -u -m iron_horse run \
  --snapshot runs/influx-source --output runs/influx-checkpoint --stage all
python -W error -m iron_horse verify runs/influx-checkpoint
```

`run` uses the API by default. Its stages are `download`, `prepare`, `develop`,
and `evaluate`. A completed snapshot can be reused offline with a fresh output
directory. We keep response pages, prepared observations, models, and predictions
under ignored `runs/`. Recorded aggregate results are read-only.

## Recorded API result

Inspect the verified November 11 qualification without network access or scientific packages:

```sh
python3 -m iron_horse summary
```

The quality-aligned run produced baseline F1 **0.379310** on **1,638 eligible test hours**.
RF F1 is zero and logistic F1 is 0.018779. The primary hypothesis remains not
evaluable because the test has only 15 positive sensor-days, below the required 20.

The [qualification report](docs/influx-qualification.md) records the real run,
quality exclusions, eligibility arithmetic, and independent replay. It uses fresh
matric pages and verified frozen soil/weather API pages, with that reuse explicit.
The [November 5 API record](docs/api-checkpoint.md) and its
[native guide](https://docs.google.com/document/d/1vI1yEyPofWDixw9hYIGxHv1by51rUK70c_Z9Vk75ZSs/edit?usp=drivesdk)
remain historical records. Use the current workflow above for new work.

## Review and project history

The [review notes](docs/REVIEW.md) identify the current commands and verified
source contract. [Validation](docs/VALIDATION.md) separates automated tests,
synthetic execution, and real API evidence.

We preserve the [preregistration](protocol/README.md), earlier experiments,
and their measured results. The [experiment index](docs/experiments.md) lists
those reports. [Historical reproduction](docs/legacy-reproduction.md) documents
the explicit CSV command and pinned implementations.

Our files remain under local review. We have not pushed this work or submitted
the checkpoint. No deployment or service change is part of this realignment.

| Path | Purpose |
| --- | --- |
| `iron_horse/` | API capture, quality policy, checkpoint models, and independent verification |
| `metadata/public_api_contract.json` | Required quality fields and accepted potential units |
| `tests/` | Synthetic contract checks, scientific windows, and offline end-to-end execution |
| `protocol/` | Preserved registration and implementation decisions |
| `results/` | Immutable aggregate experiment records |
| `docs/` | Current workflow, readiness, review, and experiment reports |
| `data/` | Data instructions and ignored local files |
| `runs/` | Ignored snapshots, caches, fitted models, and predictions |
