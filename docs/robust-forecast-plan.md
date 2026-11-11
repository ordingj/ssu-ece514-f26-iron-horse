# Soil-water median and absolute-error forecast plan

We will test whether typical daily drift and an absolute-error training loss
improve reported soil-water change forecasts. This follows the fixed continuous
forecast screen, where persistence had the lowest pooled MAE. All available
months have already informed exploration. This is not a new untouched test,
an amendment to the original preregistration, or a sensor-fault diagnosis.

## Fixed inputs and first comparison

We will reuse the verified continuous experiment's covered soil-water examples.
The four outcome probes, 24-hour change labels, history predictors, purged
June/July/August folds, and scored rows remain identical. We will verify parent
artifact hashes and its recorded receipt. We will not change cleaning rules,
impute targets, add predictors, or refit the old squared-error forests.

For each location and fold, we will compare:

- Persistence: predict zero change.
- Median change: predict the median signed 24-hour change in permitted training rows.
- Existing squared-error forest: reuse its recorded history-only predictions.
- Absolute-error forest: clone that forest pipeline and change only its criterion
  to `absolute_error`. Fit its preprocessor and regressor on the same training rows.

The cloned forest retains 200 trees, depth 6, minimum leaf 24, seed 514,
two worker threads, and every other estimator parameter. This gives 12 new
forest fits. The training-median reference has no predictor-based model.

## Larger-change assessment

Before scoring, we will calculate each location/fold's 90th percentile of
absolute training changes, using linear quantile interpolation. A scored
example is in the larger-change subset only when its absolute observed change
is strictly greater than that cutoff. Ties are excluded. We will report empty
subsets explicitly and will not lower the cutoff to obtain more cases.

This is an outcome-based diagnostic subset, not an alert available at issuance.
It changes no cleaning or forecast eligibility. Every method uses identical
rows within a subset. We retain overall MAE as the primary descriptive metric.
We also report RMSE, signed bias, counts, local dates, per-location/month scores,
equal-group mean MAE, and daily errors. Repeated hours are not independent events.

## Conditional second comparison

The first comparison fails its descriptive improvement check if the expanding
absolute-error forest's pooled overall MAE is not lower than both persistence
and the expanding training-median reference. This is a fixed exploratory trigger,
not a significance test or formal success criterion.

If triggered, we will fit 12 additional absolute-error forests using issue times
in the preceding 90 × 24 hours, with the same strict outcome-end purge.
The lower issue-time endpoint is included. The forest parameters, history
columns, scoreable rows, and preprocessing procedure remain fixed. History
features may use observations before that fitting window, as available at
issuance. Only the rows used for fitting and the fitted parameters change.

We will compare this window with persistence and its own training-median
reference. We will keep the first comparison's larger-change cutoffs for all
second-comparison scores so that the evaluated subsets do not move. We will
compare window predictions on the same rows. No other model or window search
is included. There will be at most 24 new forest fits.

## Provenance and verification

Models and row-level predictions stay in a new ignored run directory. We will
record the plan and implementation hashes, parent input/model hashes, training
statistics, model parameters, prediction hashes, and trigger result. The new
run will refuse an existing output or a path inside the parent or recorded
results. Scientific manifests will list only declared outputs.

A separate verifier will recount training splits, medians, quantiles, subset
membership, prediction identities, preprocessing statistics, model replays,
metrics, and the conditional decision. We will add a new report with commands,
aggregate evidence, and explicit limitations. Earlier experiments and raw
observations remain unchanged. We will not push or submit this work.
