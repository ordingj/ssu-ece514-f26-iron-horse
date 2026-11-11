"""Shared time windows, weather decoding, fitting, and metrics for Iron Horse."""
from __future__ import annotations
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score


ROOT = Path(__file__).resolve().parents[1]


H = 3_600_000_000_000


TZ = 'America/Los_Angeles'


START, JUNE, JULY, END = [pd.Timestamp(s, tz=TZ).tz_convert('UTC') for s in
    ('2026-01-01', '2026-06-01', '2026-07-01', '2026-09-01')]


GRID = pd.date_range(START, END, freq='h', inclusive='left')


MATRIC = [f'SDI-12-LS-US915-{i}' for i in (1, 2, 4, 5)]


WEATHER = 'SDI-12-LS-US915-3'


RAW = 'device_frmpayload_data_data_sum'


FLAG = 'device_frmpayload_data_s_flag'


SOIL_RE = r'^device_frmpayload_data_(water|temp)_SOIL[1-4]?$'


NUMBER = r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'


SIGNED = rf'[+-]{NUMBER}'


ATMOS = re.compile(rf'[0-9A-Za-z](?:{SIGNED}){{17}}')


TOKENS = re.compile(SIGNED)


WEATHER_FIELDS = {'solar_w_m2': 0, 'precipitation_mm': 1, 'wind_speed_m_s': 4,
                  'air_temperature_c': 7, 'relative_humidity_percent': 10}


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False, default=str) + '\n')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def decode_weather(raw):
    raw = str(raw).strip()
    if not ATMOS.fullmatch(raw):
        return [np.nan] * len(WEATHER_FIELDS)
    numbers = [float(v) for v in TOKENS.findall(raw)]
    result = []
    for field, index in WEATHER_FIELDS.items():
        value = numbers[index]
        if not math.isfinite(value) or value in {-9999., -9992., -9991., -9990.}:
            value = np.nan
        elif field == 'relative_humidity_percent':
            value = round(value * 100, 2)
        result.append(value)
    return result


def ns(index):
    return pd.DatetimeIndex(index).as_unit('ns').asi8


def partition(t):
    if START <= t < JUNE:
        return 'train' if t + pd.Timedelta(hours=24) < JUNE else 'purged'
    if JUNE <= t < JULY:
        return 'validation' if t + pd.Timedelta(hours=24) < JULY else 'purged'
    if JULY <= t < END:
        return 'test' if t + pd.Timedelta(hours=24) < END else 'purged'
    return 'outside'


def slopes(hourly, width):
    output = np.full(len(hourly), np.nan)
    minimum = 4 if width == 6 else 18
    for i in range(len(hourly)):
        y = hourly[max(0, i + 1 - width):i + 1]
        x = np.arange(len(y), dtype=float)
        good = np.isfinite(y)
        if good.sum() >= minimum:
            xx, yy = x[good], y[good]
            output[i] = np.sum((xx - xx.mean()) * (yy - yy.mean())) / np.sum((xx - xx.mean()) ** 2)
    return output


def window_stat(times, values, total=False):
    good = np.isfinite(values)
    times, values = times[good], values[good]
    csum = np.concatenate(([0.], np.cumsum(values)))
    anchors = ns(GRID)
    left = np.searchsorted(times, anchors - 24 * H, side='right')
    right = np.searchsorted(times, anchors, side='right')
    count = right - left
    sums = csum[right] - csum[left]
    result = np.full(len(GRID), np.nan)
    present = count > 0
    result[present] = sums[present] if total else sums[present] / count[present]
    return result


def latest(times, values):
    anchors = ns(GRID)
    indices = np.searchsorted(times, anchors, side='right') - 1
    valid = indices >= 0
    valid[valid] &= anchors[valid] - times[indices[valid]] <= H
    result = np.full(len(GRID), np.nan)
    result[valid] = values[indices[valid]]
    return result


class FrozenPreprocessor(TransformerMixin, BaseEstimator):
    """Fit imputation, constant-column removal and scaling on fit data only."""
    def fit(self, X, y=None):
        a = np.asarray(X, dtype=float)
        keep = []
        for j in range(a.shape[1]):
            good = a[np.isfinite(a[:, j]), j]
            if len(good) and np.ptp(good) > 0:
                keep.append(j)
        if not keep:
            raise ValueError('No varying numeric predictors in fitting data')
        self.keep_ = np.array(keep)
        x = a[:, self.keep_]
        self.medians_ = np.nanmedian(x, axis=0)
        imputed = np.where(np.isfinite(x), x, self.medians_)
        self.means_ = imputed.mean(axis=0)
        self.scales_ = imputed.std(axis=0, ddof=0)
        self.scales_[self.scales_ == 0] = 1
        return self

    def transform(self, X):
        x = np.asarray(X, dtype=float)[:, self.keep_]
        missing = ~np.isfinite(x)
        imputed = np.where(missing, self.medians_, x)
        return np.concatenate(((imputed - self.means_) / self.scales_, missing.astype(float)), axis=1)


def probabilities(model, features):
    matrix = model.predict_proba(features)
    classes = model.named_steps['classifier'].classes_
    where = np.flatnonzero(classes == 1)
    return matrix[:, where[0]] if len(where) else np.zeros(len(features))


def scores(target, prediction):
    cm = confusion_matrix(target, prediction, labels=[0, 1])
    return {'f1': float(f1_score(target, prediction, zero_division=0)),
            'precision': float(precision_score(target, prediction, zero_division=0)),
            'recall': float(recall_score(target, prediction, zero_division=0)),
            'tn': int(cm[0, 0]), 'fp': int(cm[0, 1]), 'fn': int(cm[1, 0]), 'tp': int(cm[1, 1])}


def coverage(inputs, labeled):
    results = []
    for (part, site), group in inputs.groupby(['partition', 'site']):
        if part in {'purged', 'outside'}:
            continue
        lab = labeled[(labeled.partition == part) & (labeled.site == site)]
        scored = lab[lab.evaluation_eligible]
        results.append({'partition': part, 'site': site, 'scheduled_nonpurged_hours': len(group),
            'forecast_eligible_hours': int(group.forecast_eligible.sum()),
            'forecast_coverage': float(group.forecast_eligible.mean()),
            'current_or_history_missing_hours': int((~group.forecast_eligible).sum()),
            'currently_dry_forecast_eligible_hours': int((group.forecast_eligible & group.currently_dry).sum()),
            'primary_input_eligible_hours': int(group.primary_input_eligible.sum()),
            'primary_hours_missing_future_label': int((lab.primary_input_eligible & lab.target.isna()).sum()),
            'evaluation_hours': len(scored), 'evaluation_coverage': len(scored) / len(group),
            'positive_hours': int((scored.target == 1).sum()), 'negative_hours': int((scored.target == 0).sum())})
    return pd.DataFrame(results)
