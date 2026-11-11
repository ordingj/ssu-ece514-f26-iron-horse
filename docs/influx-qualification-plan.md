# Live InfluxDB qualification plan

Team Iron Horse | November 11, 2026

We qualify the deployed quality-enabled API with the existing checkpoint code.
We retain the registered January–August calendar, threshold, eligibility gates,
model grid, score cutoff, tie rules, freeze order, and evaluation rules.
We do not tune around the observed results.

We request fresh matric-potential pages with metadata and quality provenance.
We reuse only the immutable November 5 soil and weather API pages, verifying
both their original manifest digest and every reused page digest. No old
matric pages enter this snapshot. We record per-page retrieval times and the
auxiliary-cache reuse receipt. This is a controlled qualification with fixed
auxiliary inputs, not a claim that every stream was downloaded on November 11.

The existing client checks response format, checksum status, finite values,
documented matric fault codes, and reported potential units. Unknown units
are excluded before hourly aggregation and labeling. Conflicting keys remain
unavailable. We do not manufacture or infer missing quality flags.

We run capture, preparation, development, and evaluation through the primary
API command. We verify source hashes and independently reconstruct all hourly
inputs, future labels, eligibility decisions, and final model predictions.
We compare source and example identities with preserved reference artifacts
only after scoring. Those references never enter fitting or source preparation.

We retain raw pages, prepared observations, models, and row-level predictions
under ignored runs/. We publish only aggregate results and provenance in the
local repository. No deployment, submission, or push is part of qualification.
