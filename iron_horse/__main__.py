"""InfluxDB checkpoint commands, recorded results, and explicit legacy reproduction."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def check_data(source):
    if not source.is_file():
        raise FileNotFoundError(f'Missing dataset: {source}. See data/README.md for the required export')
    manifest = json.loads((ROOT / 'metadata/source_manifest.json').read_text())
    if source.stat().st_size != manifest['bytes']:
        raise ValueError('Dataset size differs from the registered export. See data/README.md')
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != manifest['sha256']:
        raise ValueError('Dataset checksum differs from the registered export. See data/README.md')
    print(f'Verified dataset: {manifest["records"]} records, SHA-256 {digest.hexdigest()}')


def summary(folder):
    result = json.loads((folder / 'results.json').read_text())
    print(f'Recorded checkpoint: {folder.name}')
    source_file = folder / 'source_summary.json'
    prep_file = folder / 'preparation.json'
    source = json.loads(source_file.read_text()) if source_file.exists() else (json.loads(prep_file.read_text()) if prep_file.exists() else {})
    if source.get('api') or source.get('source_kind') == 'public_influx_api':
        print('Source: InfluxDB API')
        print('Matric quality policy: ' + source.get('quality_policy', 'not recorded in this historical snapshot; a quality-aligned rerun is pending'))
    if 'metrics' not in result:
        print(f'Primary hypothesis: {result["status"]}')
        print('Scores unavailable: ' + result.get('reason', 'This run has not produced test scores'))
        return
    print(f'Baseline F1: {result["metrics"]["drying_trend"]["f1"]:.6f}')
    print(f'Random forest F1: {result["metrics"]["random_forest"]["f1"]:.6f}')
    print(f'Logistic regression F1: {result["metrics"]["logistic_regression"]["f1"]:.6f}')
    print(f'Eligible test sensor-hours: {result["test_examples"]}')
    print(f'Primary hypothesis: {result["status"]}')
    print(f'Positive sensor-days: {result["sensor_days_by_class"]["1"]} (20 required)')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('run', help='Run the InfluxDB API workflow; use run --help for stages', add_help=False)
    commands.add_parser('doctor', help='Check live metadata and matric quality support')
    commands.add_parser('legacy-csv', help='Reproduce the historical CSV workflow', add_help=False)
    verification = commands.add_parser('verify', help='Independently verify an API checkpoint under runs/')
    verification.add_argument('folder', type=Path)
    verification.add_argument('--verify-source', action='store_true', help=argparse.SUPPRESS)
    verification.add_argument('--legacy-csv', action='store_true', help='Verify an explicit historical CSV reproduction')
    recorded = commands.add_parser('summary', help='Show the recorded API result without network access')
    recorded.add_argument('--folder', type=Path, default=ROOT / 'results/influx-qualification-2026-11-11')
    dataset = commands.add_parser('check-data', help='Check the exact source file for legacy CSV reproduction')
    dataset.add_argument('--source', type=Path, default=ROOT / 'data/ihv-sensor-data-2026.csv')
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {'run', 'legacy-csv'}:
        if arguments[0] == 'run':
            from .api_checkpoint import main as execute
        else:
            from .checkpoint import main as execute
        try:
            execute(arguments[1:])
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            parser.exit(2, f'{error}\n')
        return
    args = parser.parse_args(arguments)
    try:
        if args.command == 'doctor':
            from .api_checkpoint import check_api
            print(json.dumps(check_api(), indent=2))
        elif args.command == 'summary':
            summary(args.folder)
        elif args.command == 'check-data':
            check_data(args.source)
        elif args.command == 'verify':
            if args.folder.resolve().is_relative_to((ROOT / 'results').resolve()):
                raise ValueError('Recorded results are read-only. Verify a local reproduction under runs/')
            if args.legacy_csv:
                from .verification import verify
                verify(args.folder, args.verify_source)
            else:
                from .api_verification import verify
                verify(args.folder)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(2, f'{error}\n')


if __name__ == '__main__':
    main()
