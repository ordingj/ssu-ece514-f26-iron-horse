# Protocol and current execution

The files in this directory preserve the registered checkpoint and its source
record. They are not rewritten when an implementation or data service changes.
The registered threshold, horizon, calendar split, eligibility gates, candidate
models, cutoff, and success rules remain fixed.

The current [API workflow](../docs/influx-workflow.md) uses a versioned public
quality contract. This changes source access and requires explicit matric unit
provenance. It is an execution adaptation, not a claim that a new source policy
was preregistered before the data were inspected.

The [source contract](../metadata/public_api_contract.json) and preparation
hashes record the active policy. The [November 11 qualification](../docs/influx-qualification.md) completes
a quality-aligned real run with explicit auxiliary-cache reuse. Recorded results retain their original source
and code identities. Sensor calibration and irrigation benefit remain unverified.
