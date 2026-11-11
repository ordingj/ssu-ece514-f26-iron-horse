"""Describe coverage exclusions after fitting, without changing rules or models."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect(audit, output):
    audit, output = audit.resolve(), output.resolve()
    if output.is_relative_to(audit) or output.exists(): raise ValueError('Choose a new directory outside the audit')
    summary = json.loads((audit / 'summary.json').read_text())
    assert (audit / 'independent_verification.json').is_file()
    inputs = ['examples.parquet', 'hourly.parquet', 'channel_metadata.json']
    for name in inputs: assert digest(audit / name) == summary['artifact_hashes'][name]
    examples = pd.read_parquet(audit / 'examples.parquet')
    hourly = pd.read_parquet(audit / 'hourly.parquet')
    info = json.loads((audit / 'channel_metadata.json').read_text())
    rows, dates = [], []
    for (outcome, site), panel in examples.groupby(['outcome', 'site']):
        for fold in summary['folds']:
            cutoff = pd.Timestamp(fold + '-01', tz='America/Los_Angeles')
            removed = panel[(panel.time + pd.Timedelta(hours=24) < cutoff) & panel.eligible_covered & ~panel.eligible_complete]
            rows.append({'outcome': outcome, 'site': site, 'fold': fold, 'removed_training_rows': len(removed),
                'past_incomplete_rows': int((~removed.past_complete).sum()),
                'mean_change': removed.target_change.mean(), 'min_change': removed.target_change.min(),
                'max_change': removed.target_change.max()})
            for date, group in removed.groupby(removed.time.dt.tz_convert('America/Los_Angeles').dt.strftime('%Y-%m-%d')):
                dates.append({'outcome': outcome, 'site': site, 'fold': fold, 'day': date,
                    'removed_rows': len(group), 'mean_change': group.target_change.mean(),
                    'min_change': group.target_change.min(), 'max_change': group.target_change.max()})
    output.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(output / 'excluded_training_windows.csv', index=False)
    pd.DataFrame(dates).to_csv(output / 'exclusions_by_day.csv', index=False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    frame = hourly.loc[pd.Timestamp('2026-01-03', tz='America/Los_Angeles'):pd.Timestamp('2026-01-07', tz='America/Los_Angeles')]
    fig, axes = plt.subplots(4, 1, figsize=(12, 9), sharex=True, layout='constrained')
    for ax, block in zip(axes, ['P', 'Cc', 'B North', 'F']):
        for key, meta in info.items():
            if meta['block'] == block and meta['kind'] == 'water':
                ax.plot(frame.index.tz_convert('America/Los_Angeles'), frame[key], lw=1, label=meta['label'] + ' ' + str(meta['slope']))
        ax.set(ylabel=block + ' VWC %');ax.legend(fontsize=6);ax.grid(alpha=.2)
    fig.suptitle('Post-hoc inspection of January 4–5 coverage-sensitive training windows\nReported water channels stay separate; gaps are unfilled; physical causes are unknown')
    fig.savefig(output / 'january-water.png', dpi=140);plt.close(fig)
    receipt = {'analysis': 'post-hoc coverage diagnosis; no new exclusions or fitted models',
        'input_hashes': {name: digest(audit / name) for name in inputs},
        'verifier_receipt_sha256': digest(audit / 'independent_verification.json'),
        'code_sha256': digest(Path(__file__)),
        'artifact_hashes': {name: digest(output / name) for name in ['excluded_training_windows.csv', 'exclusions_by_day.csv', 'january-water.png']}}
    (output / 'diagnosis.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inspect(args.audit, args.output)
