# Alternative target audit plan

We will audit numerical alternatives before fitting another classifier.
This is an exploratory audit of already inspected January-August observations.
We will preserve the original protocol and checkpoint.

## Fixed comparison grid

- Thresholds: -100, -200, -300, -400, and -500 kPa.
- Forecast horizons: 6, 12, 24, and 48 elapsed hours.
- Outcome families: new dry event, future dry occurrence, and future dry majority.

This gives 60 candidates. Thresholds are numerical sensitivity values, not
crop-specific or calibration-validated irrigation recommendations.

## Outcome definitions

A new dry event requires current hourly median potential strictly above the
candidate threshold. Its outcome is any accepted raw threshold reading in
the future window, following the registered event logic.

Future dry occurrence uses that same observed future outcome and includes
currently dry locations. Future dry majority also includes currently dry
locations. It requires at least half of the expected future hourly medians
to be at or below the threshold.

For majority labels, missing future bins remain unknown. A positive label
requires enough observed dry bins to meet the threshold. A negative label
requires that even all unknown bins becoming dry could not meet it.
Other majority windows remain unlabeled.

## Coverage and calendar

We keep the current history requirement: at least four valid medians in the
last six hours and 18 in the last 24 hours, including the current bin.
We require observations in at least five-sixths of the future hourly bins,
rounded up, with no raw observation gap above two hours, including endpoints.
The 24-hour case therefore retains the original 20-of-24 rule.

Training remains January-May, validation June, and test July-August 2026.
A candidate forecast must satisfy `t + horizon < next partition boundary`.
The purge changes with the forecast horizon. Historical inputs can cross an
earlier boundary. We keep all four locations on the same split.

## Episodes and baselines

We count observed raw threshold episodes with the existing six-hour wet reset
and two-hour gap censoring, at each candidate threshold. Counts are distinct
observed onsets, not proof of independent events. We also count episodes with
eligible positive forecast opportunities strictly before onset.

We compare always-defer, always-positive, current-state persistence, and a
six-hour linear-trend rule. The new-event trend rule requires a negative trend
and projects the current potential to the horizon. Future occurrence also
triggers on currently dry soil. Majority uses the projected midpoint potential.
These are simple references, not tuned models.

## Outputs and interpretation

We will report every candidate, including degenerate classes and rejected
windows. We will report counts by partition, positive and negative sensor-days,
locations contributing each class, coverage, episode support, and baseline
scores. We will show the original class-support check separately.

No candidate will be adopted automatically. We will interpret training and
validation support before discussing a revised question. Test comparisons
remain descriptive because the outcomes have already been inspected.
