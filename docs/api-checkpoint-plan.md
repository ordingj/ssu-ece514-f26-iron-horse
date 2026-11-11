# API checkpoint rerun plan

We rerun the linked checkpoint with the public InfluxDB API as the source.
We preserve the original guide, protocol, CSV, and recorded results.

## Fixed scope

- Calendar: January 1 through August 31, 2026, in America/Los_Angeles.
- Training: January through May. Validation: June. Test: July and August.
- Target: any accepted potential at or below -500 kPa in the next 24 hours.
- Retain the original current-state, history, future-coverage, and strict boundary gates.
- Retain the 24 predictor slots, candidate models, cutoff, tie rules, and bootstrap.
- Freeze fitted preprocessing and models before constructing test labels.
- September observations do not enter this comparison.

## Source and interpretation

We request metadata and fixed inclusive-start, exclusive-stop windows.
We cache complete response pages, queries, retrieval times, and SHA-256 hashes.
We follow every non-null cursor, including pages without decoded readings.
We never substitute a private token, raw CSV, or old derived cache.
We verify each expected device's block and slope against our captured inventory.

The API supplies decoded numbers. It omits raw packets and soil quality flags.
Its matric decoder accepts two-number responses without our separate Cc unit check.
It rejects framed response forms accepted by our local decoder.
We use at most three concurrent requests to the public service.
Its inventory describes the deployment snapshot rather than historical locations.
We cannot reconstruct those unavailable checks from the API response.
We therefore report this as an API-based rerun rather than an exact source reproduction.
We do not retune settings to recover the old baseline number.

## Validation and delivery

We test pagination, empty pages, bounds, metadata, conflicts, and frozen-cache checks.
We test shared feature assembly and run the complete group suite because input preparation changes.
We replay future windows, eligibility, baseline predictions, confusion counts, and F1 independently.
We compare scheduled and eligible counts with the prior CSV result.
We create a new instructor-facing guide with commands, syntax, and eligibility arithmetic.
We retain response pages and row-level outputs under ignored runs/ and keep changes local.
