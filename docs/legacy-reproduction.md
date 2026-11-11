# Historical reproduction

The primary project command uses the public InfluxDB API. This page covers
preserved experiments with different source or code contracts.

## Registered CSV checkpoint

The CSV workflow is explicit:

```sh
python -m iron_horse check-data --source /path/to/ihv-sensor-data-2026.csv
python -W error -u -m iron_horse legacy-csv \
  --source /path/to/ihv-sensor-data-2026.csv \
  --output runs/csv-reproduction --stage all
python -W error -m iron_horse verify runs/csv-reproduction \
  --legacy-csv --verify-source
python -m iron_horse summary --folder results/checkpoint-2026-11-04
```

The exact file has 40,338,376 records and 11,574,346,721 bytes. Its SHA-256 is
recorded in [the source manifest](../metadata/source_manifest.json).
An arbitrary export with the same filename is not a substitute.
This command retains the registered checksum check, decoder, eligibility,
model settings, and split. Source exports remain outside Git.

## Previously prepared API runs

The November 5 API capture did not request matric quality provenance.
Current preparation rejects it as a new quality-aligned source. Its models,
predictions, and aggregate results remain preserved. Verification under its
original contract requires the matching implementation, available at commit
`445f149`. Use a separate checkout and the environment pinned there.

```sh
git show 445f149:docs/api-checkpoint.md
git show 445f149:iron_horse/api_checkpoint.py
```

Use that checkout's documented verifier against the unchanged saved output.
Do not edit a preparation receipt or insert assumed quality flags to make it
pass newer code guards. Code-hash mismatches identify different implementations.

The source snapshot and model binaries remain under ignored `runs/` locally.
The repository contains aggregate records and hashes, not those full artifacts.

## Research modules

The [experiment index](experiments.md) links the remaining analyses and their
fixed plans. Their reports specify required saved parent runs. A current
API checkpoint is not automatically a valid replacement for those parent caches.
