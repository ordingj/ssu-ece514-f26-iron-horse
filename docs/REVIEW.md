# Group repository review

We realigned the project around the public InfluxDB API. The main workflow uses
quality-aware frozen responses, fixed checkpoint models, and independent replay.
The files remain under local review. We have not pushed or submitted this work.

## Main entry points

| Command | Purpose |
| --- | --- |
| `python -m iron_horse doctor` | Check live metadata and matric quality support |
| `python -m iron_horse run` | Capture, prepare, fit, freeze, and evaluate API inputs |
| `python -m iron_horse verify PATH` | Independently replay a prepared API run |
| `python -m iron_horse summary` | Inspect the saved API result without network access |
| `python -m iron_horse legacy-csv` | Explicitly reproduce the registered CSV workflow |
| `python -m iron_horse verify PATH --legacy-csv` | Verify an explicit CSV reproduction |

The [README](../README.md), [workflow](influx-workflow.md), and
[data instructions](../data/README.md) describe the same primary route.
The independent verifier lives in `iron_horse/api_verification.py`.
The standalone script remains a compatibility entry point.

## Data acceptance

The [contract](../metadata/public_api_contract.json) requires explicit matric
format, checksum, potential-unit, and temperature-completeness provenance.
We exclude unknown potential units before hourly aggregation. Missing or
inconsistent quality stops the run. Visible numeric or quality conflicts make
the whole observation key unavailable.

We check source and scientific-cache hashes before development and evaluation.

The [readiness record](influx-readiness.json) reports successful quality-enabled
requests and a passing doctor check on November 11. It retains the November 6
HTTP 400 as a historical observation. Live responses, rather than the presence
of source code alone, establish support for the required request fields.
This task performs no deployment or service change.

## Preserved evidence

The default summary shows the verified November 11 quality-aligned result.
The [qualification report](influx-qualification.md) records fresh matric pages,
explicit auxiliary-cache reuse, and independent replay. The November 5 API
result remains a historical metadata-only source record. The earlier CSV
checkpoint, preregistration, experiments, and aggregate records remain unchanged.
The [experiment index](experiments.md) separates research reports from current
workflow instructions. Pinned-code reproduction is documented separately.

The [validation record](VALIDATION.md) distinguishes synthetic end-to-end
execution from live capability evidence. Test fixtures remain explicitly synthetic.
Raw pages, models, and row-level predictions remain ignored. The checkout grants
no cluster, database, or account privileges.

## November 11 qualification review

Both independent axes reviewed the same frozen slice. The validation receipt
records its checksum and the passing checks. The scientific code and registered
rules remain unchanged. The final documentation closeout adds these review results.

### Standards

Zero blockers and zero follow-ups. The review confirms preserved evidence,
explicit auxiliary-cache reuse, unknown-unit exclusions, and ignored raw data.

### Intent

Zero blockers and zero follow-ups. The review confirms the live contract,
real pipeline, independent replay, exact reference parity, and unchanged
insufficient-support conclusion. No all-stream refresh or calibration is claimed.
