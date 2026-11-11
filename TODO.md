# Group project repository

- [x] Realign the project repository to the InfluxDB API workflow.
  - Make API execution, verification, and recorded summaries the main commands.
  - Require explicit matric quality provenance and exclude unknown potential units.
  - Reconcile setup, data instructions, review notes, and research entry points.
  - Preserve previous experiments and retain an explicit legacy CSV command.
  - Verify live capabilities and record upstream dependencies without deployment.

The [current workflow](docs/influx-workflow.md) and primary commands now use
the API with explicit matric quality provenance. The full suite passes 108 tests,
including synthetic end-to-end execution and both independent verifier entries.
The [live check](docs/influx-readiness.json) now records quality-request HTTP 200.
The [real qualification](docs/influx-qualification.md) completes the follow-up
with independent replay. No deployment or push was performed.

- [x] Rerun the checkpoint from the public InfluxDB API.
  - Preserve the linked guide, prior results, threshold, calendar splits, and model settings.
  - Cache bounded metadata-enabled API pages and verify source and preparation hashes.
  - Report API validity differences and independently replay labels and scores.
  - Create a new group guide with commands and keep the repository local.

The [API run record](docs/api-checkpoint.md) preserves the November 5 baseline
F1 of 0.379310 on 1,381 eligible test hours. That metadata-only capture did not
record matric quality provenance. Its suite passed 97 tests.

- [x] Compare median regression and absolute-error boosting on the fixed transfer splits.
  - Freeze model settings and retain all existing split, outcome, predictor, and scoring rules.
  - Reuse verified persistence, training-median, and forest predictions unchanged.
  - Fit preprocessing only on permitted rows and disable random boosting validation.
  - Verify all 38 new fits and all prediction and score identities independently.
  - Add a new group report with commands and preserve prior experiments locally.

The [new report](docs/alternative-models.md) records 38 new pipelines and
88 passing tests. Median regression improves full-season spatial error over
both constants. Boosting improves summer spatial error. Both improve pooled
chronological error, while held-block future median regression is essentially
tied with persistence. Earlier experiments remain unchanged.

- [x] Compare block-only and block-plus-time soil-water transfer.
  - Fix spatial, temporal, and pooled-control splits before fitting.
  - Reuse covered examples and common history predictors without block identifiers.
  - Exclude held-block labels and preprocessing data in both transfer designs.
  - Compare the same summer evaluation rows and report full-season spatial results separately.
  - Independently replay splits, preprocessing, predictions, and scores.
  - Add a new group report with commands and preserve all earlier experiments locally.

The [new report](docs/block-transfer.md) records 19 new fits and 83 passing
tests. Spatial transfer is more favorable than future transfer on matched
summer rows. Persistence remains best there, and the full-season spatial
forest loses to the training median. Prior experiments remain unchanged.

- [x] Test training-median baselines and absolute-error soil-water forests.
  - Preserve covered examples, predictors, earlier fits, and all prior results.
  - Fix training-only median and larger-change definitions before fitting.
  - Change only the forest loss in the first comparison.
  - Run the fixed 90-day window comparison only if the first forest fails both constants.
  - Verify predictions, counts, metrics, and training-only preprocessing independently.
  - Add a new group report with commands and keep changes local for review.

The [new report](docs/robust-forecast.md) records 24 new forest fits, the
conditional 90-day comparison, and 77 passing tests. Forest errors improve,
but persistence remains best overall. The August improvement and small
larger-change subset remain explicit. No prior result or cleaning rule changed.

- [x] Explore cleaning choices and continuous forecasting models.
  - Fix outcomes, forecast timing, cleaning variants, and comparisons before fitting.
  - Preserve original observations, protocol, checkpoint, and earlier audits.
  - Compare persistence, recent trend, and learned models without future predictors.
  - Report chronological performance, location differences, coverage, and uncertainty.
  - Add a new report with commands and keep all work local for review.

The [new report](docs/continuous-forecast.md) records 192 fitted models and
71 passing tests. Persistence has the lowest pooled MAE for both outcomes.
Coverage filtering changes water-model behavior without proving sensor faults.
The original checkpoint remains unchanged. We have not pushed.

- [x] Prepare our standalone group repository for local review.
  - Include our current code, protocol, tests, and recorded results.
  - Document setup, execution, eligibility, and source requirements.
  - Preserve the original source files and Git history.
  - Keep the project files local until review is complete and a push is approved.

The packaging checks passed 42 tests in both checkouts. Our full reproduction
and independent replay match the recorded checkpoint.

- [x] Present the checkpoint guide and project prose to the instructor in our group voice.

- [x] Count distinct drying episodes and measure warning lead times.
  - Define wet recovery and missing-data rules before counting.
  - Attribute hourly examples and frozen test predictions to observed episodes.
  - Compare reset rules and preserve the original checkpoint.
  - Document commands, every onset, warning times, and independent verification.

The current group suite passes 108 tests. Our [episode report](docs/drying-episodes.md)
records one training, two validation, and nine test episodes under a six-hour
wet reset. The baseline warns before eight test episodes. RF warns before none,
and logistic regression warns before one.

- [x] Audit alternative target definitions.
  - Compare the fixed 60-candidate grid without fitting RF or adopting a target.
  - Preserve original observations, protocol, checkpoint, and episode results.
  - Independently verify counts, metrics, episode identities, and aggregate tables.

Our [target report](docs/alternative-targets.md) records every candidate and the
limits of new-event and future-state targets. No alternative target was adopted.

Our [review notes](docs/REVIEW.md) and [validation](docs/VALIDATION.md) record
the included files and reproduction evidence.

## Next step

We are reviewing the API-first package locally before pushing. We have not pushed
this work or changed repository access.

- [x] Qualify a fresh real API run after the publisher enables matric quality fields.
  - Confirm live quality support with doctor and historical responses.
  - Fetch fresh matric pages and record verified auxiliary-page reuse.
  - Refit, freeze, evaluate, and independently replay the complete checkpoint.
  - Preserve existing results without deployment, submission, or push.

The [qualification report](docs/influx-qualification.md) records baseline F1
0.379310 on 1,638 eligible test hours. All hourly inputs and test predictions
match the preserved reference. Positive support remains below the formal minimum.

- [x] Compare matric patterns with other sensors before choosing rules or models.
  - Preserve readings, existing validity rules, and all recorded experiments.
  - Compare jumps, near-zero runs, gaps, and daily temperature associations.
  - Keep individual probes and terrain positions separate.
  - Document evidence, coverage, uncertainty, and commands for review.

Our [sensor comparison](docs/sensor-comparison.md) records distinct wetting,
temperature, near-zero, and missing-data patterns. We have chosen no new
cleaning rules or models. The evidence does not establish physical causes.
