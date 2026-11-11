# Sensor data

The primary workflow reads the public InfluxDB API and freezes responses under
ignored `runs/`. It needs no database account, token, or local sensor export.
Read the [workflow](../docs/influx-workflow.md) before starting a capture.

```sh
python -m iron_horse doctor
python -W error -u -m iron_horse run \
  --snapshot runs/influx-source --output runs/influx-checkpoint --stage all
python -W error -m iron_horse verify runs/influx-checkpoint
```

New matric observations require metadata and explicit quality provenance.
The quality policy excludes unknown potential units before aggregation or labeling.
The [contract](../metadata/public_api_contract.json) defines accepted flags.
On November 11 the live endpoint accepts quality-enabled requests and the doctor
check passes. The client still stops if required provenance is unavailable.

Each page receipt records exact bounds, measurement, flags, pagination, retrieval
time, and checksum. A completed snapshot is reused without a network request.
Use separate snapshot and output directories. Choose a fresh output for each run.
Do not infer missing observations or quality flags from previous experiments.

The [historical reproduction guide](../docs/legacy-reproduction.md) covers the
explicit CSV command and exact export checksum. That file is not required for
the primary workflow or its synthetic tests.

Do not commit response pages, source exports, prepared row-level data, model
binaries, credentials, or database dumps. Preserve actual observations and keep
synthetic fixtures identified as synthetic.
