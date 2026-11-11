# Vineyard block-transfer evaluation plan

We will test two different generalization questions for reported soil-water
change: transfer to another block within the observed season, and forecasting
later readings in a block whose labels never enter fitting. A pooled time-only
control will help distinguish pooling from withholding the target block.
All four blocks and all months have already informed exploration. These are
exploratory evaluations, not untouched tests or changes to the preregistration.

## Fixed observations and model

We will reuse verified covered soil-water examples from the continuous run.
The four single-probe outcomes, 24-hour change labels, observation validity,
and history predictors remain unchanged. Each block retains its own target.
We will not pool probe readings into an outcome or add block identifiers,
block-specific columns, auxiliary sensors, or future weather as predictors.

Each model will use the same common numeric history columns: current value,
lags, trailing summaries, slopes, and known calendar terms. We will clone the
existing history pipeline with absolute-error criterion, 200 trees, depth 6,
minimum leaf 24, seed 514, and two worker threads. Preprocessing will fit
only permitted training rows. No parameter or feature search is included.

The held-out block's recent readings are available as forecast inputs. Its
outcome labels, fitting statistics, and calibration estimates cannot enter
training. This tests a newly modeled block with recent sensor history, not
a location with no measurements. Shared weather and proximity limit geographic
independence. Four blocks do not establish transfer to other vineyards.

## Evaluation designs

| Design | Fitting rows | Evaluated rows | Forest fits |
| --- | --- | --- | ---: |
| Block only | All covered January–August examples from the other three blocks | All covered examples of the held block, within that season | 4 |
| Block plus time | Covered examples from the other three blocks whose 24-hour outcomes end strictly before the evaluated month | Held block in June, July, or August, with outcomes ending strictly before the following month | 12 |
| Pooled time control | Covered examples from all four blocks whose outcomes end strictly before the evaluated month | All four blocks in that month, with the same strict end purge | 3 |

For the full-season spatial design, all outcomes must end strictly before
September 1 local time. There is no internal month purge in its full-season
training or evaluation. Training can include later-season readings from other
blocks when a held-block observation comes from earlier in the season.
This is intentional retrospective spatial transfer, not prospective forecasting.

The chronological designs use the original strict horizon purge and expanding
earlier history. We will not add the 90-day window, since the current question
concerns validation design and pooling. There will be exactly 19 new fits.

## Comparable scores and references

We will score block-only transfer on all eligible January–August held-block
examples. We will also score it on a common summer subset: issue times in
June, July, and August whose outcomes end strictly before the next month.
This subset must match all scored rows of both chronological designs exactly.
We will not compare full-season and summer MAEs as if they used the same cases.

For every fit, persistence predicts zero change. A second constant reference
predicts the signed median change of that fit's pooled training rows. Held-block
labels cannot determine the transfer median or preprocessing. The pooled time
control can use earlier target-block labels, which is part of its distinct claim.

We will report MAE, RMSE, signed bias, counts, local dates, per-block and
per-month results, equal-group mean MAE, and daily errors. Scores use reported
water percentage points. We will compare model errors with persistence on the
same cases within each design and scope. The pooled control has more training
rows than a held-block fit, so their difference is not a pure effect of location.

We will keep the earlier larger-change assessment in its original report.
This experiment will not redefine event cutoffs or choose another model based
on a favorable split. An easier spatial task does not establish improved
prospective forecasting. All results and empty support groups will be explicit.

## Reproduction and evidence

The parent loader will verify saved examples, predictions, controls, code,
plan, and verification implementation. Models and row-level predictions stay
in a new ignored run. Declared outputs will include split counts, training
medians, model hashes, predictions, score tables, figures, and provenance.
Existing outputs and recorded results cannot be overwritten.

A separate verifier will check held-block exclusion, strict time cutoffs,
common evaluation identities, predictor columns, training-only preprocessing,
model replays, baselines, and all aggregate scores. We will add a new group
report with commands and limitations. Prior code, source observations, protocols,
and results remain unchanged. We will not push or submit this experiment.
