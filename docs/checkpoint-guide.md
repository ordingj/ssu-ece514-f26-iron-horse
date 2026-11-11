Team Iron Horse | November 4 2026 | Current RF preregistration

We ran our pipeline from the complete sensor CSV through test scoring. The drying-trend baseline F1 is 0.379310 on 1,638 eligible July and August sensor-hours. This guide explains each step, the commands that run it, and the Python syntax behind it.

# Checkpoint result

| Method | F1 | Precision | Recall |
| --- | --- | --- | --- |
| Drying trend baseline | 0.379310 | 0.394872 | 0.364929 |
| Random forest | 0.000000 | 0.000000 | 0.000000 |
| Logistic regression | 0.018779 | 1.000000 | 0.009479 |
| Always defer | 0.000000 | 0.000000 | 0.000000 |

There are 211 positive examples and 1,427 negative examples. The RF minus baseline F1 difference is -0.379310.

The descriptive paired 95 percent interval for that difference is [-0.489187, -0.080556]. The registered outcome is NOT EVALUABLE.

Our test set has only 15 positive sensor-days. The preregistration requires at least 20 sensor-days containing each class. We can report the baseline score, but our primary hypothesis lacks its required test support.

Primary success requires RF F1 at least 0.05 above the drying-trend baseline and RF recall at least 0.80. Logistic regression is an additional benchmark. It does not determine primary success.

Our outcome forecasts an observed sensor threshold. It does not establish an optimal irrigation action. We treat this evaluation as exploratory because late-season observations informed threshold selection.

The observations reflect existing vineyard management. Results apply to the monitored locations and do not validate sensor calibration.

## How to use this guide

We show shell commands from the project directory and explain Python syntax from iron_horse/checkpoint.py. The Python blocks are excerpts, not separate programs. Our reported numbers come from the original saved run. We provide reproduction commands for our standalone group repository.




# 1 Project and environment

We have packaged our code and recorded aggregate results in a standalone group repository. Our project files are under local review and have not been pushed. After we push the reviewed files, the repository can be cloned with:

```sh
git clone https://github.com/ordingj/ssu-ece514-f26-iron-horse.git
cd ssu-ece514-f26-iron-horse
```

Our local checkout already contains the package. We can inspect the recorded result without loading the large dataset:

```sh
python3 -m iron_horse summary
```

We use the following commands to create the pinned environment, activate it in bash or zsh, and run the checks:

```sh
uv venv --python 3.14.0 .venv
uv pip install --python .venv/bin/python -r requirements.lock.txt
source .venv/bin/activate
python -W error -m unittest discover -s tests -p 'test_*.py'
```

Windows PowerShell uses these install and activation commands after creating the environment:

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements.lock.txt
.venv\Scripts\Activate.ps1
python -W error -m unittest discover -s tests -p 'test_*.py'
```

Tests use synthetic time windows and small recorded decoder fixtures. They do not need the full CSV or a live service.

# 2 Dataset and pipeline execution

We keep the 11.6 GB sensor export outside Git. Reproduction requires the exact file, supplied separately. We document its size and checksum in `data/README.md`. The pipeline accepts `data/ihv-sensor-data-2026.csv` or an explicit source path.

We use a new output directory for each reproduction. These commands use bash or zsh:

```sh
SOURCE="/path/to/ihv-sensor-data-2026.csv"
OUT="runs/reproduction"
python -m iron_horse check-data --source "$SOURCE"
python -W error -u -m iron_horse run \
  --source "$SOURCE" --output "$OUT" --stage all
python -W error -m iron_horse verify "$OUT" --verify-source
```

The all stage runs prepare, develop, and evaluate in order. We can also run the three stages separately:

```sh
python -W error -u -m iron_horse run \
  --source "$SOURCE" --output "$OUT" --stage prepare
python -W error -u -m iron_horse run --output "$OUT" --stage develop
python -W error -u -m iron_horse run --output "$OUT" --stage evaluate
```

We use either the all command or the three staged commands, with a fresh output directory for each run. Preparation creates no future labels. Development selects and freezes both pipelines. Evaluation opens and scores the test targets once.

`runs/` holds ignored local outputs. The recorded November 4 result stays under `results/checkpoint-2026-11-04/`. Its original source and provenance remain separate from a reproduction under this layout.

# 3 Verify and clean the source export

During preparation, we read the complete 40,338,376-record export. The file contains individual measurements, not independent modeling examples. It verifies the checksum before processing.

```
# SOURCE is the path chosen in Step 2.
shasum -a 256 "$SOURCE"
```

Expected SHA-256

```
5770aeb5645c181e636f4f87ccb52555e7327525f389b82f91c0cdc18bfa9b04
```

The registered file has 11,574,346,721 bytes. preparation.json records the exact source path, hash, environment, and implementation hashes.

We use Polars to scan the large CSV and select the four matric sensors, the weather station, and the registered soil channels. Exact duplicates collapse. Conflicting values or metadata at one device, measurement, and timestamp become missing.

```
raw = pl.scan_csv(source, infer_schema_length=0)
selected = raw.filter(chosen).unique()
cleaned = selected.group_by(
    ["device_name", "measurement", "time"]
).agg(...)
```

We check block and terrain metadata against metadata/devices.json. The CSV fields slope and label describe the sensor. Neither is the target.

# 4 Decode readings without inventing values

We decode supported numeric and framed responses with the matric decoder. It rejects documented fault codes and invalid checksums. Cc readings with unresolved first-field units stay missing. No missing digits, unit conversion, or calibration are inferred.

```
reading = decode_response(raw)
value = matric_value(device, raw)
# Cc fields with unknown kPa units return NaN.
```

| Matric sensor | Valid kPa records | Excluded records |
| --- | --- | --- |
| 1 | 231,324 | 0 |
| 2 | 309,029 | 128,668 |
| 4 | 228,493 | 485 |
| 5 | 231,137 | 79 |

Weather uses fixed packet field positions. Soil values require valid finite readings and valid transmission flags. cleaning_audit.json and decode_audit.json record the checks and exclusions.




# 5 Build one hourly example per sensor location

We interpret calendar boundaries in America/Los_Angeles. A UTC grid preserves consecutive elapsed hours through daylight saving time. Each location supplies its own future target.

```
# A reading exactly on the hour stays in that hour.
bins = pd.to_datetime(times, utc=True).ceil("h")
hourly = pd.Series(values, index=bins).groupby(level=0).median()
trend_6h = slopes(hourly_values, 6)
trend_24h = slopes(hourly_values, 24)
```

We calculate current potential as the median of valid readings in (t - 1 hour, t]. Each trend is a least-squares slope against elapsed hours. Missing medians are omitted, not interpolated.

| Predictors | Time rule |
| --- | --- |
| Current matric potential | Median in the current right-closed hour |
| Six-hour and 24-hour trends | Past hourly medians including the current bin |
| Soil water content and temperature | Latest valid same-block probe reading at most one hour old |
| Air temperature humidity solar and wind | Valid observation means over the past 24 hours |
| Rainfall | Sum of unique valid interval amounts over the past 24 hours |

The schema contains 24 numeric predictor slots before fit-time removal. Soil slots keep terrain positions and probe numbers separate. Multiple devices in one same-block slot use their median. Device IDs, coordinates, descriptive labels, and future values are excluded from predictors.

# 6 Apply input eligibility and future label rules

```
input_ok = (
    (current_potential > -500)
    & (valid_hours_in_last_6 >= 4)
    & (valid_hours_in_last_24 >= 18)
)
# Future window: strictly after t, through t + 24 hours.
label_ok = (occupied_future_bins >= 20) & (max_gap_hours <= 2)
target = any(valid_future_reading <= -500)
```

We require the same future coverage for positive and negative labels. The maximum gap includes both window boundaries. We never impute unobserved future readings. An example enters scoring only when input_ok and label_ok are true.




# 7 Split by calendar time and purge boundary targets

| Partition | Calendar period | Role |
| --- | --- | --- |
| Training | January 1 through May 31 | Fit candidate preprocessing and models |
| Validation | June 1 through June 30 | Choose registered model settings |
| Test | July 1 through August 31 | Score frozen pipelines once |

```
# Apply to every location on the same calendar boundary.
retain = t + pd.Timedelta(hours=24) < next_boundary
```

The strict comparison removes the final 24 hours of each partition. Historical features can use observations from an earlier partition. We never randomly split measurement rows.

| Partition | Scheduled | Eligible | Positive | Negative |
| --- | --- | --- | --- | --- |
| test | 5,856 | 1,638 | 211 | 1,427 |
| train | 14,396 | 8,476 | 24 | 8,452 |
| validation | 2,784 | 1,283 | 45 | 1,238 |

Our scheduled counts exclude purged hours. Each count is a sensor-hour, so observations can be correlated within a location and across time.

## Coverage and exclusions

| Test exclusion stage | Sensor-hours |
| --- | --- |
| Missing current reading or inadequate history | 889 |
| Already dry among hours with sufficient history | 3,292 |
| Eligible inputs but inadequate future coverage | 37 |
| Eligible for test scoring | 1,638 |

These stages partition the scheduled test examples. coverage.csv also reports each location and partition, including forecast coverage and evaluation coverage. Missing physical evidence remains missing.




# Eligibility explained in detail

## What scheduled hours means

One example is one matric-sensor location at one clock hour t. Scheduled hours are possible decision times before checking whether usable readings exist.

The July and August test period contains 62 days. Four locations produce 62 x 24 x 4 = 5,952 possible sensor-hours.

We retain an hour only when its complete 24-hour target window ends strictly before the next partition boundary. For testing, that boundary is September 1 at 00:00 in America/Los_Angeles.

t + 24 hours < September 1 at 00:00

August 30 at 23:00 is retained: its target window ends August 31 at 23:00. August 31 at 00:00 is excluded: its window ends exactly at the September 1 boundary.

All 24 decision hours on August 31 are excluded at each location. That removes 24 x 4 = 96 sensor-hours, leaving 5,952 - 96 = 5,856 scheduled test sensor-hours.

These 5,856 hours still include missing readings and already-dry soil. They are the starting grid for the remaining eligibility checks.

The same rule removes the final 24 hours before the June 1 training boundary and July 1 validation boundary. Historical features can cross an earlier boundary because those observations were already available at decision time.

## The four eligibility gates

1. Current reading: the median of valid matric readings in (t - 1 hour, t] must be strictly above -500 kPa. Hours at or below -500 kPa are already dry and are excluded from the advance-warning score.
2. Historical coverage: we require at least four valid hourly potential medians in the last six hours and at least 18 in the last 24 hours. Both historical windows include the current hourly bin.
3. Future coverage: we require valid observations in at least 20 of the next 24 hourly bins. No gap can exceed two hours, including the gaps at both window boundaries. We apply these rules to positive and negative labels equally.
4. Partition boundary: the full 24-hour future window must end strictly before the next partition begins. This is the boundary exclusion described above.

## How the test count is obtained

The exclusions below are sequential and do not overlap. Each rejected sensor-hour is counted at its first failing stage.

* We start with 5,856 scheduled test sensor-hours after boundary exclusions.
* We exclude 889 hours with a missing current reading or insufficient historical coverage. This leaves 4,967 hours with sufficient input history.
* We exclude 3,292 of those hours because the soil is already at or below -500 kPa. This leaves 1,675 eligible advance-warning inputs.
* We exclude 37 additional hours because future observations cannot establish a sufficiently observed label. This leaves 1,638 hours for scoring.

5,856 - 889 - 3,292 - 37 = 1,638

## Forecast inputs and scoring labels have different requirements

Future coverage determines whether we can score a prediction afterward. It does not supply predictor values or information available to the model at time t. A forecast can be issued from eligible inputs even when its later outcome cannot be scored.

Missing optional soil or weather predictors do not exclude an otherwise eligible example. Retained predictors use fitting-set medians and missingness indicators. Future matric readings are never imputed.

We score the baseline and both classifiers on exactly the same 1,638 examples. The counts are P: 820, Cc: 779, B North: 39, and F: zero.

All 1,242 F sensor-hours with sufficient input history are already dry. F therefore contributes no eligible test examples to this advance-warning task.

## Hourly eligibility is separate from study support

A sensor-day is a location and local calendar-day pair. A positive sensor-day contains at least one eligible positive example. A mixed sensor-day can count toward both positive and negative support.

The 20-positive-sensor-day minimum is a separate check on whether the hypothesis is evaluable. It does not remove individual hours from the score. This run has 15 positive sensor-days, so the formal claim is not evaluable even though baseline F1 is measurable.

Overlapping future windows and repeated observations from each location make sensor-hours correlated. The paired seven-day bootstrap keeps locations together to describe this dependence.


# 8 Fit preprocessing on the fitting partition only

We fit each candidate's preprocessing on January through May. Validation values do not influence medians, column retention, means, or standard deviations. We refit these quantities on training plus validation for the selected pipeline.

```
# Keep numeric columns that vary among observed fit values.
medians = np.nanmedian(retained_fit_values, axis=0)
numeric = np.where(missing, medians, values)
scaled = (numeric - fit_means) / fit_population_std
features = np.concatenate((numeric, missing.astype(float)), axis=1)
```

RF uses the unscaled numeric matrix. Logistic regression uses scaled numeric values. Both append unscaled zero-or-one missingness indicators. Entirely missing and constant numeric predictors are removed. There is no outcome-driven feature selection, class weighting, resampling, or calibration.

# 9 Select the registered model settings

```
RandomForestClassifier(
    n_estimators=300, criterion="gini", max_features="sqrt",
    bootstrap=True, random_state=514,
    max_depth=depth, min_samples_leaf=leaf)
LogisticRegression(
    C=C, l1_ratio=0, solver="lbfgs",
    tol=0.0001, max_iter=1000)
```

In scikit-learn 1.9.1, l1_ratio=0 specifies L2 without the deprecated penalty argument. Other settings use that version's defaults. Positive scores at least 0.70 predict irrigate. The score is not a calibrated probability of irrigation need.

| Model | Setting | June F1 |
| --- | --- | --- |
| RF | depth 4, leaf 10 | 0.000000 |
| RF | depth 4, leaf 30 | 0.000000 |
| RF | depth 8, leaf 10 | 0.000000 |
| RF | depth 8, leaf 30 | 0.000000 |
| Logistic | C 0.1 | 0.000000 |
| Logistic | C 1 | 0.000000 |
| Logistic | C 10 | 0.000000 |

Selected RF settings: {'max_depth': 4, 'min_samples_leaf': 30}. Selected logistic C: 0.1. Tied RF scores favor shallower trees, then larger leaves. Tied logistic scores favor smaller C.

Training contains 24 positive examples among 8,476 eligible sensor-hours. Every registered candidate has June F1 of zero. The registered tie rules determine both selections.




# 10 Freeze both pipelines before test targets

After June selection, we refit both complete pipelines on eligible January through June examples. We save the fitted models and model_freeze.json before constructing July and August labels.

```
final = model_pipeline(kind, selected).fit(fit[X], fit[y])
joblib.dump(final, model_path)
# Freeze code, source/schema receipts, selected settings and model hashes.
# evaluate verifies these records before writing test_unlock.json.
```

Original checkpoint implementation commit: 021e58e88b731f90de423a057eb91b7a9751323c. Model freeze time: 2026-11-05T00:27:45.891943+00:00. The evaluation stage refuses a second test unlock in the same output directory.

# 11 Calculate baseline predictions and test scores

```
baseline_prediction = (
    (trend_6h_kpa_per_h < 0)
    & (current_potential_kpa + 24 * trend_6h_kpa_per_h <= -500)
)
F1 = 2 * TP / (2 * TP + FP + FN)
precision = TP / (TP + FP)
recall = TP / (TP + FN)
```

The baseline has no fitted settings. It extrapolates the six-hour drying trend 24 hours forward. Always-defer predicts zero for every eligible example. Every method uses the same test rows. Undefined F1 is zero.

| Method | TN | FP | FN | TP |
| --- | --- | --- | --- | --- |
| Drying trend | 1309 | 118 | 134 | 77 |
| RF | 1427 | 0 | 211 | 0 |
| Logistic | 1427 | 0 | 209 | 2 |
| Always defer | 1427 | 0 | 211 | 0 |

Baseline arithmetic: 2 x 77 / (2 x 77 + 118 + 134) = 0.379310.

# 12 Report uncertainty and the registered decision

We resample seven consecutive local calendar days with replacement from the full July and August calendar. We keep all locations together and truncate to 62 days. We use 2,000 resamples with seed 514. We take the 2.5th and 97.5th percentiles of the paired RF minus baseline F1 difference.

Test support includes 15 sensor-days with positive examples and 62 with negative examples. A mixed day counts in both sets. Both development partitions contain both classes: True.




# Results by location

| Block | Eligible | Positive | Baseline F1 | RF F1 | Logistic F1 |
| --- | --- | --- | --- | --- | --- |
| P | 820 | 128 | 0.468293 | 0.000000 | 0.000000 |
| Cc | 779 | 58 | 0.239521 | 0.000000 | 0.000000 |
| B North | 39 | 25 | 0.529412 | 0.000000 | 0.148148 |

Block F contributes no eligible test examples. All 1,242 F hours with sufficient history are already dry, so they are excluded from the advance-warning score. Its test F1 is not scored.

RF improvement requirement met: False. RF recall requirement met: False. The registered primary outcome is not evaluable. Our checkpoint demonstrates an end-to-end pipeline that produces the preregistered baseline number. The RF hypothesis remains not evaluable.

# Saved outputs

```
python -m json.tool "$OUT/results.json"
python -m json.tool "$OUT/development.json"
python -m json.tool "$OUT/model_freeze.json"
```

| Artifact | What it records |
| --- | --- |
| protocol/preregistration.txt and protocol/source.json | Current canonical protocol snapshot and source link |
| protocol/IMPLEMENTATION.md | Fixed decoding and modeling choices |
| preparation.json | CSV checksum environment and artifact hashes |
| cleaning_audit.json and decode_audit.json | Metadata checks conflicts and decoding exclusions |
| feature_schema.json | Ordered predictor slots |
| development.json | Class counts all June trials and selected settings |
| model_freeze.json and test_unlock.json | Freeze and test-opening records |
| coverage.csv and results.json | Exclusions coverage metrics support and outcome |
| test_predictions.csv | Local row-level predictions for independent verification |
| Local run logs | Execution output when redirected by the caller |

Our independent verification command

```
python -W error -m iron_horse verify \
  "$OUT" --verify-source
```

We independently verify the run by replaying every scored future window and recounting baseline predictions, confusion counts, and F1. It also verifies artifact hashes and freeze ordering.

## Protocol and interpretation

Canonical preregistration

https://docs.google.com/document/d/1d3L8nC-RSejREsTm4iYgjuQil-4KQ5jSpYOVoJcekd0/edit

# Exploratory episode audit

We counted the distinct observed threshold episodes behind the hourly labels.
Using a six-hour wet reset, the 24 positive training hours precede one episode.
We counted two validation episodes and nine test episodes.

The baseline warned before eight test episodes, with a median first warning
8.33 hours ahead among detected episodes. RF warned before none. Logistic
regression warned before one, about 24 minutes ahead.

The [episode report](drying-episodes.md) lists every onset and warning time.
It also reports uncertain starts, the one-hour and 24-hour reset checks, and
unchanged hourly scores. This is an exploratory analysis, not a protocol change.
