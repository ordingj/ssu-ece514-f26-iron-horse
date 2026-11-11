# Decoder fixtures

The time-window and model-selection tests use synthetic observations with
known outcomes. They are not vineyard measurements.

`cc-boundaries/scale_change_evidence.csv` and
`cc-boundaries/format_change_evidence.csv` contain small recorded Cc response
examples from the existing October 8 diagnosis. The decoder tests also retain
recorded packet examples inline. These are real historical observations,
not synthetic benchmark data. They test field interpretation and checksums.
They do not establish sensor calibration or model performance.

The source hashes and original paths are recorded in
[the import manifest](../../provenance/import-manifest.json).
