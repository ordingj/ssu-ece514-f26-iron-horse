# Project validation

## November 11: real quality-enabled qualification

The live endpoint accepts `include_quality=true` and the doctor check passes.
The [qualification report](influx-qualification.md) records the real pipeline,
source provenance, eligibility arithmetic, fixed models, and limitations.
The [validation receipt](qualification-validation-2026-11-11.json) records the checks.

The complete suite passes **108 tests** with warnings treated as errors.
The default-summary regression failed before the result selection changed,
then all five CLI checks passed. All 21 pinned packages remain compatible.
Only the default recorded-result path and its tests changed in Python code.
The scientific implementation, source adapter, and registered rules retain
all baseline hashes. No dependency changed.

The real capture contains 127 fresh matric pages and 1,415 verified frozen
auxiliary pages. No matric page was reused. We excluded 128,668 distinct
unknown-unit potential keys before aggregation or labeling. The complete run
fits, freezes, and evaluates both classifiers. Independent replay verifies
all 1,542 page hashes, 23,324 hourly inputs, 23,036 nonpurged labels, and
1,638 test predictions. The baseline F1 is 0.3793103448275862.

A separate audit matches every accepted potential timestamp and value,
all 33 input columns and their dtypes, every test identity and prediction,
and both classifier score arrays to the preserved reference. That reference
entered neither preparation nor fitting. This proves processing parity for
the controlled snapshot with fixed auxiliary inputs. It does not establish
physical calibration or a newly uninspected confirmation period.

Earlier result artifacts and registered protocol files remain unchanged.
Raw pages, models, and row-level predictions remain under ignored runs/.
Both independent review axes report zero blockers and zero follow-ups.
Final syntax, JSON, local links, shell examples, sizes, aggregate hashes, prose,
and staged secret checks pass. No deployment, submission, or push was performed.

## November 6: InfluxDB workflow realignment

The complete suite passes **108 tests** with warnings treated as errors.
The [validation receipt](workflow-validation.json) records the current code and checks.
Tests first failed for the new API defaults and quality requirements, then passed.
A separate summary regression first failed for unscored runs, then passed.

The synthetic end-to-end test constructs a complete fixed-calendar API snapshot,
runs preparation, candidate fits, model freeze, and evaluation through the primary
command, then independently replays both classifiers and all scored labels.
It tests both verification entry points and confirms exclusion of an unknown-unit
observation. These fixtures are synthetic rather than vineyard measurements.

The real [capability check](influx-readiness.json) observed metadata HTTP 200 and
quality-enabled HTTP 400 at that check. The primary download command returned
a clear error before creating a snapshot directory. A real quality-aligned run
was pending at that time; the November 11 section records its completion.
The November 6 realignment performed no deployment or fresh real fit.
The dependency check reports 21 compatible pinned packages.
Both Standards and Intent reviews report zero blockers and zero follow-ups.
Source syntax, shell examples, links, JSON hashes, prose, and staged secrets pass.

Earlier scientific results, plans, protocol files, and inventory retain their hashes.
The current [workflow](influx-workflow.md) supersedes the operational commands below.
Historical command transcripts remain records of their named implementations.

## Historical validation records

We validated our standalone package on November 4, 2026. We reproduced the
original checkpoint in a clean clone outside the School checkouts.
Our only external project input was the separately supplied sensor CSV.

## Environment and tests

A fresh Python 3.14.0 environment installed all 21 pinned packages.
`uv pip check --python .venv/bin/python` reported compatible dependencies.
Both the working checkout and a clean clone passed all 42 tests with warnings
treated as errors:

```sh
python -W error -m unittest discover -s tests -p 'test_*.py'
```

The source checkout's existing 54 checks also passed before extraction.
The group suite includes the current protocol, decoder fixtures, shared
calculations, and five command checks. The source chart and export-capture
suites are outside this group's current pipeline and are not imported.

The recorded summary runs without the CSV or scientific imports. Missing data
produces a clear message. The command entry point refuses runs that would write
under `results/`. Tests verify that the recorded checkpoint stays unchanged.

The runtime checks used macOS. The guide includes the Windows interpreter and
activation paths, but no native Windows runtime check was performed.

## Complete reproduction

The code-bearing local commit is recorded in [validation.json](validation.json).
It precedes this reproduction's development labels. The run used these commands
from a clean clone, with `SOURCE` set to the existing registered CSV:

```sh
python -W error -u -m iron_horse run --source "$SOURCE" --output runs/packaging-reproduction --stage all
python -W error -m iron_horse verify runs/packaging-reproduction --verify-source
python -m iron_horse check-data --source "$SOURCE"
```

The source checksum matched. Both refitted pipelines were frozen before test
labels. Independent replay checked all 1,638 scored future windows, baseline
predictions, confusion counts, F1 values, artifact hashes, and freeze order.

All 16 compared result fields match the original, including model settings,
all method scores, class counts, location scores, support checks, and the paired
interval. Six artifacts match their original bytes: coverage, development
trials, development coverage, decoder audit, cleaning audit, and feature schema.

| Result | Value |
| --- | --- |
| Baseline F1 | 0.3793103448275862 |
| Random forest F1 | 0 |
| Logistic regression F1 | 0.018779342723004695 |
| Eligible test sensor-hours | 1,638 |
| Positive sensor-days | 15 |
| Formal hypothesis | Not evaluable because 20 positive sensor-days are required |

This is a reproduction of an exploratory evaluation. It does not create a new
uninspected test period. Original result files remain unchanged.

Full local outputs, models, and caches remain under ignored
`runs/packaging-reproduction/`. Only the small validation receipt enters Git.

## Source and file checks

The import manifest verifies source and destination hashes. Shared and current
calculation definitions retain their source syntax trees, with documented path
changes. Device routing values match the source while omitting unused identity
and coordinate fields.

Python syntax, JSON, local Markdown links, file sizes, and symlink checks pass.
All imported files are regular files below 10 MiB. New and changed prose passes
the configured check. Staged secret scans pass without suppressions.

The repository declares no formatter or type-check wrapper. The complete group
test suite, syntax and file checks, dependency check, clean-clone execution,
and independent replay cover this organization change.

## Documentation revision

We revised the guide and project prose for the instructor in our group voice.
We checked prose, local links, command references, unchanged result tables,
and the rendered native guide. We changed no pipeline code, protocol rules,
or recorded results, so another full experiment was unnecessary.

We are reviewing the package locally before pushing. We have not pushed project
files or changed repository access.

## Episode audit

We added a separate episode audit after the original checkpoint. The complete
group suite passes 50 tests with warnings treated as errors. Eight new synthetic
checks cover episode recovery, gaps, uncertainty, and warning attribution.

We ran the audit against the complete saved reproduction. It checked input
hashes and replayed the original labels. A separate check matched all 12
primary onset identities, all sensitivity totals, and every warning count and
lead-time endpoint. The [episode report](drying-episodes.md) and
[verification receipt](../results/episodes-2026-11-04/independent_verification.json)
record the results.

No model, original score, protocol rule, or recorded checkpoint file changed.
Another model fit was unnecessary. We ran the full group suite because the
new module introduces episode grouping and forecast attribution.

Independent Standards and Intent reviews found no issues in the episode audit.
Final Python syntax, JSON, local links, shell blocks, file sizes, provenance,
original-result byte comparisons, and the staged secret scan passed.

## Alternative target audit

The full suite passes 57 tests with warnings treated as errors. Seven new
synthetic checks cover candidate horizons, future endpoints, majority-label
uncertainty, current-state eligibility, purges, trend references, and threshold
parameters. We ran the full suite because the shared audit loader and episode
threshold interface changed.

The real-data audit completed all 60 planned candidates. It reproduced the
original -500 kPa, 24-hour class counts, test eligibility, and baseline F1.
A separate verifier matched all 180 partition summaries, 720 baseline metric
rows, and every threshold spell identity. The [new report](alternative-targets.md)
and [receipt](../results/target-audit-2026-11-04/independent_verification.json)
retain the evidence. We visually checked the generated training-support figure.

The earlier episode audit reproduces its four CSV outputs byte for byte after
the shared-loader change. Its primary, sensitivity, and hourly metric summaries
also match. Original protocol and checkpoint files remain unchanged.
No real-data classifier fit was needed for this descriptive audit.

Independent Standards and Intent reviews found no issues in the target audit.
All 60 candidate summaries reconcile to the independently checked count and
metric tables. Syntax, JSON, local links, shell blocks, file sizes, provenance,
original artifact bytes, and the staged secret scan passed.

## Comparison with other sensors

The full suite passes 63 tests with warnings treated as errors. Six new
synthetic checks cover missing-hour run boundaries, observed-window coverage,
strict Cc temperature, paired daily centering, minimum paired-day coverage,
and exclusion of conflicting weather keys.
We ran the full suite because the new module adds source aggregation and
cross-channel comparisons. No model fit is needed for this descriptive work.

The real-data comparison preserves all prior validity rules and recorded runs.
Its separate checker matches the frozen potential series, 31 case identities
and boundaries, 364 response rows, 31 case summaries, and 192 monthly
associations. It checks all three common gaps directly in the source cache,
plus samples of 120 individual soil-hour medians and 30 weather hour-field
aggregates. The source samples do not constitute a full decoder replay.

The [new report](sensor-comparison.md), [fixed plan](sensor-comparison-plan.md),
and [receipt](../results/sensor-comparison-2026-11-04/independent_verification.json)
record definitions, coverage, uncertainty, and commands. We visually checked
all eight figures. The extra April 10 contrast plot was selected after the
first response table and is disclosed in the report and summary.

Accepted weather aggregates exclude conflicting keys while raw availability
still counts received records. The new regression checks both a mixed-validity
hour and an hour containing only a conflicting packet. The source has zero
conflicting weather keys. After the fix, all six CSV tables, eight figures,
and two row-level diagnostic caches match the preceding audit byte for byte.

The Standards review reports zero findings. The Intent review's weather-conflict
finding is resolved by the validity filter and regression. Both reviews report
zero remaining blockers and zero follow-ups on the revised snapshot.
Final syntax, JSON, local links, shell syntax, sizes, input and code hashes,
prior-artifact byte comparisons, prose, and staged secret checks pass.

## Continuous forecasting exploration

The full suite passes 71 tests with warnings treated as errors. Eight added
checks cover exact target endpoints, trend units, partial and complete coverage,
missing endpoints and lags, future-predictor isolation, strict fold purges,
paired scores, overwrite protection, and scientific artifact scope.
We ran the full suite because the new module builds predictors, filters
examples, fits regressions, and records model provenance.

The complete run fits 192 fixed models and records 164,328 prediction rows.
Independent verification checks all 46,648 examples, 6,792 sampled predictor
values, all fitted training preprocessors, and every saved prediction.
It verifies 300 location/month/stratum score rows, 24 pooled rows, 48 coverage
rows, 7,074 daily errors, and 144 common-row comparisons. The
[report](continuous-forecast.md) and
[receipt](../results/continuous-forecast-2026-11-04/independent_verification.json)
retain the results. All three figures were visually inspected.

The initial manifest included incidental macOS metadata. A targeted regression
now keeps only declared scientific outputs. A manifest-only repair preserved
every numerical artifact hash and verified unchanged scientific source syntax.
The [repair record](../provenance/continuous-forecast-2026-11-04/manifest-repair.json)
and source patch retain both code hashes. This repair required no model refit.

The post-hoc coverage diagnosis runs separately after verification. Its inputs
match verified artifact hashes. The exclusion table recounts the removed
training windows by site, fold, and date. It adds no cleaning rule or model.

All 24 exclusion summaries and their date counts independently match the
verified examples. Reversing the retained source patch reconstructs the exact
original fitting-source hash. The Standards review reports zero findings.
The Intent review's coverage wording and rounding corrections are resolved.
Both final review axes report zero blockers and zero follow-ups.
Final syntax, JSON, local links, shell syntax, sizes, provenance hashes,
prior-artifact bytes, prose, and staged secret checks pass.

## Soil-water median, loss, and window comparison

The full suite passes 77 tests with warnings treated as errors. Six new
synthetic checks cover training medians and quantiles, rolling-window endpoints,
the strict label purge, absolute-error leaf behavior, unchanged controls,
strict larger-change membership, empty subsets, the conditional trigger,
and output protection. The full suite was required because the new module
adds fitting, conditional execution, and new scoring subsets.

The experiment fits 12 expanding absolute-error forests. Its fixed trigger
then runs 12 90-day fits. The separate verifier checks all 24 reference rows,
training-only preprocessors, new model replays, forest parameter identity
apart from criterion, and unchanged squared-error controls. It checks all
48,181 prediction rows, 168 location/month/stratum scores, 14 pooled rows,
2,072 daily errors, and the conditional decision. It confirms unchanged
evaluation identities and unchanged larger-change cutoffs across windows.

The [report](robust-forecast.md), [plan](robust-forecast-plan.md), and
[receipt](../results/robust-forecast-2026-11-05/independent_verification.json)
retain the evidence. We visually checked the generated figure. No cleaning
rule, outcome, predictor, original protocol, or earlier result changed.

The Standards review reports zero findings. The Intent review reports no
scientific or implementation blockers. Its minor table-rounding correction is
resolved. Final syntax, JSON, local links, shell syntax, sizes, hashes,
parent-artifact checks, prior scientific bytes, prose, and staged secret checks
pass. The runtime and independent-replay receipts remain valid after these
documentation-only corrections.

## Vineyard block-transfer experiments

The full suite passes 83 tests with warnings treated as errors. Six new
synthetic checks cover complete target-block exclusion, intentional later-season
data in the spatial design, strict outcome-end purges, the pooled chronological
control, common-summer membership, separate score scopes, and output protection.
The full suite was required for new split semantics, pooled fitting, and scoring.

The experiment fits four spatial, 12 block-plus-time, and three pooled time-only
forests. Independent verification checks all 19 splits and fitted preprocessors,
held-block exclusion, common history columns, baseline medians, and model
parameters. It replays 98,604 predictions, 204 block/month/scope metric rows,
12 pooled rows, and 5,154 daily errors. It verifies identical 6,883 summer
evaluation identities and outcomes for every method in each design.

The [report](block-transfer.md), [fixed plan](block-transfer-plan.md), and
[receipt](../results/block-transfer-2026-11-05/independent_verification.json)
retain the evidence. We visually checked both figures. The full-season spatial
assessment contains 19,102 location-hours across 208 dates. Its score is kept
separate from the matched summer scope. No original observation, protocol,
earlier scientific code, or recorded result changed.

Independent Standards and Intent reviews report zero blockers and zero
follow-ups. The report's pooled, monthly, per-block, and equal-group scores
match the recorded tables. Final syntax, JSON, local links, shell syntax,
file sizes, parent and output hashes, prior scientific bytes, prose, and
staged secret checks pass. Documentation-only closeout does not invalidate
the runtime and independent-replay receipts.

## Median-regression and boosting comparison

The full suite passes 88 tests with warnings treated as errors. Five new
synthetic checks cover conditional-median behavior with a large target residual,
fixed boosting iterations without automatic validation, finite predictions
with missing inputs, explicit unknown-model failure, and protection of both
parent directories and existing outputs. The full suite was required for two
new model forms and their fitting, prediction, and provenance behavior.

The real-data run fits 38 pipelines on the unchanged 19 transfer splits.
Independent verification checks every split, training-only preprocessor,
estimator setting, and new prediction. It compares preprocessing with the
corresponding forest and checks all 19 median-regression objectives against
the feasible constant-median objective. Boosting completes 100 iterations
without automatic early stopping or random validation.

All 98,604 old control rows remain unchanged. The verifier checks all
164,340 comparison predictions, 340 block/month/scope score rows, 20 pooled
rows, and 8,590 daily errors. It confirms identical summer cases for all
methods and designs. The [report](alternative-models.md),
[plan](alternative-models-plan.md), and
[receipt](../results/alternative-models-2026-11-05/independent_verification.json)
retain the evidence. We visually checked the four-panel figure.

No prior observation, outcome, predictor, split, code, protocol, or scientific
result changed. The new settings are fixed and untuned. The small held-block
chronological median-regression advantage is documented as essentially a tie.

Independent Standards and Intent reviews report zero blockers and zero
follow-ups. The report's relative gains, near-tie interpretation, and monthly
and block-level tables match the retained evidence. Final syntax, JSON,
local links, shell syntax, sizes, code and artifact hashes, both parent
hash chains, all prior scientific bytes, prose, and staged secret checks pass.
Documentation-only closeout does not invalidate the passing runtime and
independent-replay receipts.


## Public API checkpoint rerun

The [new API guide](api-checkpoint.md) records the fixed January–August rerun.
The complete suite passes 97 tests with warnings as errors. Nine new synthetic
checks cover pagination, metadata, nanosecond timing, conflicts, frozen pages,
causal feature timing, and incidental operating-system files.
The test-first run failed because the API module did not yet exist.

The shared assembly refactor reproduces all 23,324 historical CSV input rows
and 33 columns exactly, including dtypes. The 21 auxiliary soil and weather
slots also match between the real API and CSV preparations, including missingness.
The source comparison uses tolerance 1e-10 for finite feature values.

The live capture contains 1,542 pages and 13,112,497 returned readings.
The independent script checks every page hash, reconstructs potential arrays,
and replays all 23,324 hourly inputs and 23,036 nonpurged labels. It verifies
1,381 test predictions, both frozen models, baseline arithmetic, and exclusions.
It confirms 257 CSV-only examples, all baseline true negatives, with no API-only
test examples or changed shared targets and baseline predictions.
The [receipts](../results/api-checkpoint-2026-11-05/independent_api_verification.json)
and [identity comparison](../results/api-checkpoint-2026-11-05/test_identity_comparison.json)
retain the evidence.

The original native guide retains its source revision. The new native guide
contains the full commands, eligibility discussion, six native tables, and
245 nonempty paragraphs matched to the local report. Named headings and lists
remain native elements. These are content and structure checks.
Dependencies pass uv pip check with 21 compatible packages. Python syntax,
shell syntax, aggregate hashes, local links, and staged secret checks pass.
Both review axes report zero blockers and zero follow-ups. No CSV, raw pages, model binaries,
credentials, prior protocol changes, or prior results enter this commit.


## API guide revision

We revised the API guide into a standalone procedure after its opening transition note.
The native document and repository guide match across 228 nonempty paragraphs and
six native tables. We removed the comparison section, reference commands, and table column.
API data limitations, eligibility arithmetic, and measured results remain intact.
Prose and shell syntax checks pass. This revision changes no code, model, or data,
so another experiment or full test run is unnecessary.
