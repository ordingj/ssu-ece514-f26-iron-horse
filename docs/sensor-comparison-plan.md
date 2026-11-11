# Sensor comparison plan

We will compare the observed matric-potential patterns with independent sensor
channels before choosing new cleaning rules or fitting models. We have sensor
data only, with no irrigation or maintenance records.

## Inputs and alignment

We will use the verified complete run and its cleaned source cache. We keep
existing duplicate, fault, checksum, unit-uncertainty, and soil-flag policies.
Potential values come from the frozen decoded observations. We use strict
Cc Celsius fields only, without truncated-temperature estimates.

We will calculate observed right-closed hourly medians for each soil device
and probe separately. Weather uses hourly means and sums of unique valid
rainfall interval amounts. Missing values remain missing. We will not carry
values forward or pool different probes.

Metadata identifies shared block and terrain position, not exact distance or
depth. The weather station is in block I. We will state these placement limits.

## Fixed descriptive screens

- Large jump: at least 100 kPa between consecutive observed hourly medians.
  We group same-direction flagged hours within six hours for case indexing.
- Near-zero run: at least 12 consecutive observed hourly medians within 1 kPa
  of zero. Missing hours break a run.
- Common gap: at least six consecutive hours without raw responses from all
  four matric devices, within their shared observed date range.

These thresholds select examples for inspection. They are not proposed fault
codes, deletion rules, or new target definitions.

## Cross-sensor comparisons

For jumps, we will compare the six preceding hourly bins with six and 24 bins
starting at the selected jump hour. A numeric comparison needs at least half
of each window observed. We will report each soil probe separately, including
its terrain, observed counts, and water-content and temperature changes.

Rain totals will include observed-bin counts. A zero sum means no rain recorded
in the available station packets, not proof of no rainfall at a target location.
We will also report simultaneous matric changes at other locations.

For near-zero runs, we will compare the first and last six bins of each run.
For common gaps, we will distinguish absent raw responses from excluded or
uninterpretable responses and compare soil-device and weather availability.

We will describe temperature associations after subtracting each local day's
mean. Each paired day needs at least 18 observed hourly pairs. We will report
monthly correlations, paired hours, and paired days. We will plot August as a
fixed late-season example. Associations do not identify physical causes.

## Case selection and limits

Plots will show the largest upward jump per location, the largest downward
jump overall, and the longest near-zero run. All cases and coverage counts
will remain in the tables, including unavailable comparisons.

We will compare evidence consistent with wetting, channel-specific behavior,
and missing-data effects. No pattern alone will be called confirmed irrigation,
a sensor fault, or a calibration correction. All prior results remain intact.
