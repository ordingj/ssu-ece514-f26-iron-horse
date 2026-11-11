# Iron Horse forecasting

We forecast observed matric-potential threshold outcomes at monitored vineyard locations
using frozen public InfluxDB API snapshots. The active source contract requires
explicit potential-unit provenance before aggregation and labeling.

## Language

**Hourly example**:
One forecast opportunity at one location and clock hour, with a future outcome over the target horizon (24 hours in the registered task).
_Avoid_: Independent event

**Positive sensor-day**:
A location and local calendar date containing at least one eligible positive hourly example.
_Avoid_: Drying episode

**Dry spell**:
A group of observed readings at or below the specified threshold (-500 kPa in the registered task) without an intervening complete wet reset or long observation gap.

**Confirmed drying episode**:
A dry spell whose onset follows the specified consecutive observed wet hours.
The onset is an observed threshold reading, not an interpolated crossing time.

**Wet reset**:
The specified number of consecutive hourly bins with observations, all strictly above the specified threshold.

**Uncertain onset**:
A dry spell without a complete observed wet reset before its first dry reading.
_Avoid_: Confirmed episode

**Warning lead time**:
Elapsed time from an eligible positive prediction to the observed episode onset.
Only predictions issued strictly before onset provide advance warning.

**Future dry occurrence**:
An observed threshold reading in the future window, including forecasts issued
when the soil is already dry.

**Future dry majority**:
At least half of the expected future hourly medians are dry.
Missing bins can leave the label uncertain.


**Source snapshot**:
A fixed set of public response pages, queries, timestamps, and hashes used throughout one run.
A snapshot is not a claim that the live database was read atomically.

**Quality policy**:
The versioned rules for accepting source provenance and reported potential units.
Unknown units remain excluded. Calibration is a separate physical question.

**Recorded result**:
An immutable aggregate outcome for the source and implementation identified by its receipts.
It is not automatically a result for the current live API or current source contract.
