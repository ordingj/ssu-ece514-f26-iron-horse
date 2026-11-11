# Fixed median-regression and boosting comparison

We will compare two additional model forms on the existing soil-water transfer
designs. Regularized median regression tests whether a simple conditional
median improves on the constant training median. Shallow absolute-error
boosting tests a different nonlinear form. This is a fixed exploratory
comparison, not an untouched test or an amendment to the preregistration.

## Inputs and splits

We will use the verified continuous examples and verified block-transfer run.
The covered soil-water outcomes, common numeric history columns, and all
19 split specifications remain unchanged. These comprise four full-season
block-only fits, 12 block-plus-time fits, and three pooled chronological fits.

Held-block labels and preprocessing observations remain excluded in both
transfer designs. The spatial design intentionally uses the other blocks
throughout the observed January–August season. Chronological fits only use
outcomes ending strictly before their evaluated month. Evaluation endpoints
retain the strict next-month purge. The held block's recent readings remain
available as inputs, without using its labels for fitting.

We will reuse persistence, training-median, and absolute-error-forest predictions
from the transfer run without changing or refitting them. Each new model must
match their evaluated identities and outcomes exactly. Full-season spatial
scores and common-summer scores remain separate. The summer comparison uses
the same 6,883 location-hours for every method and design.

## Model settings fixed before fitting

Both models use the same training-only preprocessor as the forest: column
selection, median imputation, standardization, and missing indicators. We will
not impute targets or add block identifiers, auxiliary channels, future weather,
or new features. Parameters are fixed for this feasibility comparison. There
is no tuning or model selection, including within training data.

| Model | Fixed settings |
| --- | --- |
| Median regression | QuantileRegressor, quantile 0.5, alpha 0.001, intercept enabled, HiGHS solver |
| Histogram gradient boosting | Absolute-error loss, learning rate 0.05, 100 iterations, maximum depth 3, at most 7 leaf nodes per tree, minimum leaf 24, L2 regularization 1, seed 514 |

The median-regression penalty is deliberately small and fixed, with predictor
scales learned from fitting data. This setting is not claimed to be optimal.
Boosting uses `early_stopping=False`, so there is no automatic random
validation subset. We will limit supported native thread pools to two threads
during fitting and prediction. Both estimators retain all other library
defaults under the pinned environment.

There will be exactly 38 new fitted pipelines: two models for each of the
19 existing splits. A failed or nonconverged fit is a failed experiment step,
not permission to silently change settings, suppress warnings, or drop a case.

## Scoring and interpretation

MAE in reported water percentage points remains the primary descriptive score.
We will also retain RMSE, signed bias, counts, local dates, per-block/month
results, equal-group mean MAE, and daily errors. We will report every fixed
model and baseline, including poor results. Full-season spatial transfer
remains retrospective, not prospective forecasting.

We will assess whether either new model improves on both constant references
on the same cases. An improvement over the forest alone is insufficient.
We will not change the scoring scope, event definition, or cleaning policy
to favor a model. The earlier larger-change assessment stays in its own report.
Only four blocks are available, and all months have already informed model
choice and diagnosis. No formal significance claim follows from this screen.

## Provenance and verification

The loader will verify both parent runs, their source code and plans, receipt
implementations, and required artifact hashes. Old predictions will be copied
unchanged into the comparison. New models and row-level predictions remain
in a new ignored run. Manifests will list only declared scientific outputs.

A separate verifier will recount splits, check held-block and temporal
exclusions, compare preprocessing with the corresponding forest, replay all
new predictions, confirm unchanged baselines, and verify every score table.
We will retain a new report with commands, limitations, aggregate evidence,
model hashes, and figures. Prior observations, code, results, protocols,
and native documents remain unchanged. We will not push or submit this work.
