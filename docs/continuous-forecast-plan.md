# Exploratory cleaning and forecasting plan

We will test whether observed sensor history can forecast next-day changes.
Our main outcome is reported soil-water content at four routed single-probe
devices. Matric potential at the corresponding locations is a comparison.
These are measured-channel forecasts. They do not label irrigation need,
plant stress, or confirmed sensor faults.

We fixed this experiment before fitting its models. All available months have
already informed our earlier sensor diagnosis. The following chronological
evaluations are exploratory. They are not newly untouched tests or a replacement
for our registered checkpoint.

## Outcomes and timing

Each hourly forecast predicts y(t+24h) − y(t). Values are observed right-closed
hourly medians, not interpolated values. Soil-water changes use reported
percentage points. Potential changes use reported kPa. The water devices are
SE01-LS-2 at P, SE01-LS-1 at Cc, SE01-LS-3 at B North, and SE01-LS-4 at F.
They share routed terrain with their matric devices, not verified exact placement.
We will not combine different probes into an outcome.

We will use three expanding chronological folds: June, July, and August.
Each fit uses only earlier issue times whose entire 24-hour outcome ends
strictly before the evaluated month. Each evaluated outcome must also end
strictly before the next month. We retain the original strict boundary purge.
History before a month is available to forecasts at its start. We do not reset
history artificially at a fold boundary. We will not tune on these month scores.

## Cleaning choices

Both choices preserve the established duplicate, conflicting-key, soil-flag,
fault, decoder, and uncertain-unit exclusions. We do not delete jumps, remove
zeros, estimate truncated Cc temperatures, or adjust potential for temperature.
We keep missing observations missing. We compare these additional coverage rules:

| Choice | Past window | Future window for scoring |
| --- | --- | --- |
| Covered | Current, exact 6-hour lag, and exact 24-hour lag observed. At least 4/6 and 18/24 recent bins observed. No missing run longer than two bins in the past 25 bins | Exact endpoint observed, at least 20/24 future bins observed, no missing run longer than two bins |
| Complete | All 25 bins from t−24h through t observed | All 24 bins from t+1h through t+24h observed |

Gap rules here use hourly observation presence. They do not reproduce the
original classifier's raw-packet gap rule. Future coverage controls score
availability, not inputs at issuance. We will report past-eligible counts
separately from examples that also have a scoreable future outcome.

We will fit each choice separately, report its coverage, and compare fitted
choices on common scored rows. A lower error after discarding cases does not
by itself establish a better cleaning rule. Complete coverage of the outcome
channel does not require complete auxiliary channels.

## Predictors and fixed models

We will fit each outcome and location separately. History predictors are the
current outcome, observed lags at 1, 6, and 24 hours, six- and 24-hour rolling
means, the 24-hour standard deviation, and six- and 24-hour slopes. Calendar
predictors are sine and cosine of local hour and day of year.

Expanded predictors add each available same-block soil channel, the block's
matric potential and strict internal temperature, and station I weather.
Each channel contributes its current value, six- and 24-hour means, six- and
24-hour changes, and observed count in the past 24 bins. Rain uses sums rather
than means in those windows. We preserve separate probe columns. No realized
future weather or future-centered transformation enters a predictor.

The fixed forecast methods are:

- Persistence: predict zero change.
- Six-hour trend: predict four times y(t) − y(t−6h), without clipping.
- Ridge regression with alpha 10, for history and expanded predictors.
- Random forest regression with 200 trees, maximum depth 6, minimum leaf 24,
  seed 514, and two worker threads, for history and expanded predictors.

We will use the existing training-only preprocessor for both regressions.
It removes constant or entirely missing fitting columns, uses fitting medians
for remaining missing predictors, adds missing indicators, and standardizes.
We will not impute targets or fit preprocessing on evaluated rows. No search
or model selection is included. These settings test feasibility, not optimality.

## Evidence and interpretation

We will report MAE, RMSE, signed bias, counts, local calendar days, and paired
MAE improvement over persistence for every location, month, coverage choice,
and method. We will also report pooled results within each outcome, equal-group
mean MAE, daily errors, and common-row coverage-choice comparisons.

For potential, we will also score forecasts issued near zero and within 24 hours
after an observed ≥100 kPa one-hour change. These are diagnostic strata based
only on available history. They are not deletion rules. Hourly examples overlap
and locations share weather, so counts are not independent replication. We
will make no significance claim from this screen.

Models, row-level examples, predictions, and hourly input data will stay under
ignored runs. We will retain aggregate tables, figures, input and model hashes,
independent verification, and a new report with commands. Prior protocols,
results, and source observations will remain unchanged. We will not push.
