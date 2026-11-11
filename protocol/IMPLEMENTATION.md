# Current project checkpoint specification

The authoritative protocol is the current Google Doc captured in `preregistration.txt`.
`source.json` records its link and modification date. The repository layout
is a portable adaptation of the qualified November 4 implementation. This run uses random forest as
the primary model and logistic regression as an additional benchmark. The dryness
threshold is -500 kPa. The score cutoff is 0.70.

## Source and decoding

Use the complete 40,338,376 record export. Its SHA-256 is
`5770aeb5645c181e636f4f87ccb52555e7327525f389b82f91c0cdc18bfa9b04`.
Verify that checksum before processing. Use native timestamps and retained source
tags to collapse exact duplicates. Conflicting values or metadata at one device,
measurement, and timestamp make that key invalid. Verify block and terrain
metadata against the captured sensor inventory before labeling.

Use `iron_horse.matric.decode_response` for supported numeric pairs and documented
framing forms. Retain its fault and checksum checks. For Cc, use
`iron_horse.cc_policy.correct` and exclude values with unknown first-field units.
Do not convert unknown units, restore missing digits, or fit a calibration.
All other accepted matric potentials retain their reported kPa values.
This policy uses existing source diagnostics before predictive results.

Use the weather decoder and field positions in `iron_horse/core.py`.
Accept complete SDI-12 responses with 17 signed numeric values.
Solar radiation uses field 0, precipitation field 1, wind speed field 4,
air temperature field 7, and relative humidity field 10 multiplied by 100.
Remove error codes -9999, -9992, -9991, and -9990 and nonfinite values. Precipitation is an interval amount.
Sum unique valid packets over the preceding 24 hours. Average other valid
weather observations over that interval. Do not fill absent weather windows.
Use the captured soil channel names and probe numbers. Nonfinite values,
conflicting keys, and transmissions with zero or conflicting soil flags are missing.

## Examples and features

Interpret calendar boundaries in America/Los_Angeles, as resolved by the existing
implementation specification. The Google Doc uses the shorthand PST. Use
consecutive elapsed UTC hours through daylight saving time.

Use current potential medians in `(t - 1 hour, t]`. Fit six-hour and 24-hour
least-squares slopes against elapsed hours, ignoring missing medians.
Require current potential above -500 kPa, four valid medians in six hours,
and 18 in 24 hours. History includes the current hourly bin.

Keep the latest valid same-block soil observation at or before t when its age
is at most one hour. Keep terrain positions and probe numbers separate.
When multiple same-block devices occupy one slot, use their median.
Choose slots from the captured channel inventory without examining outcomes.
Exclude device IDs, coordinates, labels, and future measurements from predictors.

The target uses any valid raw observation at or below -500 kPa in `(t, t + 24 hours]`.
Both target classes require at least 20 occupied future hourly bins. No gap,
including either boundary, can exceed two hours. Do not impute future readings.

## Split and model selection

Use January through May for training, June for validation, and July through
August for testing. Require `t + 24 hours < next partition boundary`.
Historical inputs can cross an earlier boundary. Construct development labels
first. Select and refit both complete pipelines before constructing test labels.

For each fit, remove predictors that are entirely missing or constant among
observed values. Fill missing retained predictors with fitting-set medians.
Append one unscaled missingness indicator per retained predictor.
RF numeric inputs remain unscaled. Logistic regression uses fitting-set means
and population standard deviations of the imputed numeric predictors.

RF uses 300 bootstrap trees, Gini splits, square-root feature sampling, and seed 514.
Search depths 4 and 8 and minimum leaf sizes 10 and 30.
Select the highest June F1 at cutoff 0.70. Ties favor shallower trees, then larger leaves.
Logistic regression searches C values 0.1, 1, and 10 with L2, lbfgs,
tolerance 0.0001, and 1,000 iterations. Ties favor smaller C.
Use scikit-learn 1.9.1 defaults for other settings. In that version,
`l1_ratio=0` selects L2 without the deprecated `penalty` argument.
Use no weighting, resampling, calibration, or further feature selection.

Save both refitted models and their hashes before test labels. Save a test-unlock
record before evaluating. Refuse another test evaluation in the same output directory.

## Baselines and reporting

The drying-trend baseline predicts irrigate only when the six-hour trend is
negative and `current + 24 * trend <= -500`. It has no tuning.
Report always-defer as an additional reference. Score all methods on the same
eligible examples. Report F1, precision, recall, confusion counts, class counts,
coverage, exclusions, and scores by location.

Both classes must occur in training and validation. Test support requires
20 sensor-days containing each class. A mixed sensor-day counts for both classes.
An undefined F1 is zero. Primary success requires RF minus baseline F1 of at
least 0.05 and RF recall of at least 0.80. Otherwise an evaluable claim fails.

Use 2,000 paired seven-day moving-block bootstrap resamples with seed 514.
Sample non-wrapping blocks from the full July through August calendar.
Keep all locations together. Truncate the last sampled block to 62 days.
Report the 2.5th and 97.5th percentiles of RF minus baseline F1.
The interval is descriptive and does not change the success rule.

The evaluation remains exploratory because late-season observations informed
the preregistration. Commit this specification and the tested implementation
before development labels. Freeze selected pipelines before test labels.
Preserve all prior documents and results. Create a new checkpoint guide.
