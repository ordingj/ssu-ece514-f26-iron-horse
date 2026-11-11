# Recorded experiments

These reports preserve completed exploratory work and its original source policy.
Each report applies to its identified source and implementation.
Use the [current API workflow](influx-workflow.md) for new experiments.

| Experiment | Report | Recorded source |
| --- | --- | --- |
| Quality-aligned qualification, November 11 | [Qualification](influx-qualification.md) | Fresh quality-enabled matric pages with verified frozen auxiliary API pages |
| API checkpoint, November 5 | [API record](api-checkpoint.md) | Metadata-enabled API snapshot without matric quality fields |
| Threshold checkpoint | [Checkpoint guide](checkpoint-guide.md) | Registered sensor export |
| Drying episodes | [Episode report](drying-episodes.md) | Saved checkpoint preparation |
| Alternative targets | [Target audit](alternative-targets.md) | Saved checkpoint preparation |
| Other-sensor comparison | [Sensor comparison](sensor-comparison.md) | Saved checkpoint preparation |
| Continuous next-day forecasts | [Continuous forecasts](continuous-forecast.md) | Saved sensor comparison and checkpoint inputs |
| Median and forest-loss comparisons | [Robust forecasts](robust-forecast.md) | Saved continuous examples |
| Block and time transfer | [Transfer report](block-transfer.md) | Saved continuous examples |
| Median regression and boosting | [Alternative models](alternative-models.md) | Saved continuous examples and transfer controls |

The continuous, episode, target, and transfer modules retain their original
input contracts. They are research entry points, not additional stages of
`python -m iron_horse run`. We have not refitted those experiments from the API.

[Historical reproduction](legacy-reproduction.md) explains pinned code and the
explicit legacy source route. Recorded scores, frozen plans, protocol files,
and aggregate receipts remain unchanged.
