# Observed drying episodes and warning lead times

Team Iron Horse | November 4, 2026 | Exploratory analysis

We counted observed threshold episodes alongside our existing hourly scores. Our 24 positive training hours all precede **one** confirmed episode at B North, beginning May 30 at 20:23 local time.

Using a six-hour wet reset, we counted one training episode, two validation episodes, and nine test episodes. The drying-trend baseline warned before eight test episodes. RF warned before none, and logistic regression warned before one.

## What an episode means

We define a dry reading as a supported, decoded matric potential at or below -500 kPa. We group readings into consecutive right-closed UTC hours. A wet hour contains observations, all strictly above -500 kPa.

We use these rules for the primary episode audit:

1. A confirmed episode starts at the first dry reading after six consecutive observed wet hours.
2. Dry readings remain in the same spell until another complete six-hour wet reset. Brief wet periods do not create new episodes.
3. A raw observation gap above two hours ends the observed spell with uncertain recovery. A following dry spell needs a new wet reset to have a confirmed onset.
4. A dry spell without a preceding wet reset has an uncertain onset. We report it separately.
5. An episode without observed wet recovery before a gap or study end has an uncertain ending. Its confirmed onset still counts.

The six-hour reset is an exploratory grouping choice. It is not an agronomic definition or proof of statistical independence. We also report one-hour and 24-hour resets.

Times mark the first observed dry reading. The physical crossing occurred between the preceding wet observation and that reading. We do not interpolate its time.

We do not require sustained dry readings. The Cc episode on August 11 consists of one accepted dry observation. This follows the original target, which uses any accepted threshold reading. It does not establish sensor calibration.

## Episode inventory

We assign episodes to the calendar partition containing their onset. We keep episodes intact across partition boundaries. The 24-hour boundary purge still applies to forecast times.

| Partition | Confirmed episodes | Uncertain onsets | Original positive hours |
| --- | ---: | ---: | ---: |
| train | 1 | 4 | 24 |
| validation | 2 | 0 | 45 |
| test | 9 | 5 | 211 |

The nine uncertain onsets are additional dry spells, not confirmed transitions. Missing observations prevent a complete event inventory.

## Warning attribution

We keep the registered input and future-label eligibility rules. Each positive hourly example is assigned to the spell containing its first future dry reading. One hourly prediction cannot receive credit for multiple future episodes.

A warning must be an eligible positive prediction issued strictly before onset, within 24 hours, and in the same calendar partition. Predictions during an existing spell remain part of the hourly scores but receive no new-episode warning credit.

We retain confirmed episodes without scored warning opportunities in the inventory. All nine confirmed test episodes have at least one scored pre-onset opportunity.

We report the baseline in all three periods. RF and logistic warning results use only the saved frozen test predictions. We do not report fitted training predictions as test performance.

## Every confirmed episode

Onsets use America/Los_Angeles. Lead time is in hours before the first observed dry reading. We show the earliest warning, which has the largest lead. CSV files also contain the latest warning and the number of warning hours.

“None” means no advance warning. “N/A” means we do not evaluate that fitted method in that period.

| Partition | Block | Observed onset, local | Positive hours | Baseline lead, h | RF lead, h | Logistic lead, h |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| train | B North | 2026-05-30 20:23 | 24 | 23.39 | N/A | N/A |
| validation | F | 2026-06-08 01:25 | 28 | 23.43 | N/A | N/A |
| validation | F | 2026-06-08 19:14 | 17 | 13.24 | N/A | N/A |
| test | P | 2026-07-09 23:05 | 20 | 1.08 | None | None |
| test | P | 2026-07-10 21:04 | 20 | 18.08 | None | None |
| test | B North | 2026-07-10 21:23 | 25 | 7.40 | None | 0.40 |
| test | P | 2026-07-11 22:37 | 28 | 8.63 | None | None |
| test | Cc | 2026-08-11 05:01 | 24 | 8.03 | None | None |
| test | Cc | 2026-08-12 00:21 | 26 | 18.36 | None | None |
| test | Cc | 2026-08-12 21:21 | 8 | 6.35 | None | None |
| test | P | 2026-08-14 23:40 | 51 | 23.68 | None | None |
| test | P | 2026-08-19 20:19 | 7 | None | None | None |

The baseline missed the P onset on August 19 at 20:19. That episode had six eligible pre-onset forecast hours. Logistic regression warned about 24 minutes before the B North onset on July 10.

## Episode results beside the original hourly scores

| Method | Hourly F1 | Hourly precision | Hourly recall | Test episodes warned | Median first-warning lead |
| --- | ---: | ---: | ---: | ---: | ---: |
| Drying trend | 0.379310 | 0.394872 | 0.364929 | 8/9 | 8.33 h |
| Random forest | 0.000000 | 0.000000 | 0.000000 | 0/9 | None |
| Logistic regression | 0.018779 | 1.000000 | 0.009479 | 1/9 | 0.40 h |
| Always defer | 0.000000 | 0.000000 | 0.000000 | 0/9 | None |

Median lead times include detected episodes only. Undetected episodes remain visible in the detection count. This table does not define episode precision or erase false alarms. The baseline still has 118 false-positive hourly predictions.

Of the 211 positive test hours, 160 precede confirmed episode onsets, 49 occur during confirmed spells, and two belong to spells with uncertain onsets. The hourly and episode summaries therefore measure different behavior.

## Sensitivity to the wet reset

| Wet reset | Training episodes | Validation episodes | Test episodes | Test episodes with scored opportunities | Baseline episodes warned |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 h | 1 | 2 | 17 | 16 | 9 |
| 6 h | 1 | 2 | 9 | 9 | 8 |
| 24 h | 1 | 1 | 3 | 3 | 3 |

Counts depend on the grouping rule. We report all three choices and do not select a reset to improve model performance. All three identify only one confirmed training episode.

## Reproduce the audit

We use a complete local run containing decoded observations and saved predictions. The small recorded aggregate result alone does not contain these inputs. The existing [checkpoint guide](checkpoint-guide.md) explains how to create a run from the registered CSV.

```sh
source .venv/bin/activate
python -W error -m iron_horse.episodes --run runs/reproduction --output runs/episode-analysis
python -W error -m unittest discover -s tests -p 'test_*.py'
```

`--run` selects the existing completed run. `--output` selects a new directory. The audit checks saved input hashes and replays labels before grouping episodes. It does not refit models, change predictions, or write inside the source run.

The command writes episode tables, positive-hour attribution, sensitivity results, and provenance. Row-level attribution stays under ignored `runs/`. We retain the small episode aggregates in [results/episodes-2026-11-04](../results/episodes-2026-11-04/).

## Validation and interpretation

We tested grouping, short wet rebounds, complete recovery, initial dry observations, long gaps, missing hours, raw threshold equality, and warning attribution. The complete project suite passes 50 tests with warnings treated as errors.

A separate check used hourly minimums, rolling wet histories, and observation-gap segments to recount onsets. It matched all 12 primary onset identities and the sensitivity totals. Independent forecast matching reproduced every reported warning count and both lead-time endpoints. See the [verification receipt](../results/episodes-2026-11-04/independent_verification.json).

We preserve the original baseline F1, model scores, split, and protocol. The registered hypothesis remains **not evaluable**. Episode counts do not replace the minimum of 20 positive sensor-days. This post hoc audit explains the data and warning behavior. It does not establish irrigation benefit.
