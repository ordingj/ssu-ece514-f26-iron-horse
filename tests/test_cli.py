"""Check the group entry point from a checkout without any sensor data."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TeamEntryPointChecks(unittest.TestCase):
    def invoke(self, *arguments):
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        return subprocess.run([sys.executable, '-W', 'error', '-m', 'iron_horse', *arguments],
                              cwd=ROOT, env=environment, text=True, capture_output=True)

    def test_help_describes_the_available_commands(self):
        result = self.invoke('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ('run', 'verify', 'summary', 'doctor', 'legacy-csv', 'check-data'):
            self.assertIn(command, result.stdout)

    def test_recorded_summary_needs_no_sensor_export(self):
        result = self.invoke('summary')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0.379310', result.stdout)
        self.assertIn('1638', result.stdout)
        self.assertIn('not_evaluable', result.stdout)

    def test_missing_dataset_has_an_actionable_error(self):
        result = self.invoke('check-data', '--source', 'data/not-present.csv')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing dataset', result.stderr)
        self.assertIn('data/README.md', result.stderr)

    def test_run_cannot_overwrite_the_recorded_checkpoint(self):
        path = ROOT / 'results/checkpoint-2026-11-04/results.json'
        before = path.read_bytes()
        result = self.invoke('legacy-csv', '--stage', 'prepare', '--output', str(path.parent),
                             '--source', 'data/not-present.csv')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Recorded results are read-only', result.stderr)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((path.parent / 'cache').exists())

    def test_run_without_data_reports_how_to_obtain_it(self):
        result = self.invoke('legacy-csv', '--stage', 'prepare', '--source', 'data/not-present.csv')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing dataset', result.stderr)
        self.assertIn('data/README.md', result.stderr)


if __name__ == '__main__':
    unittest.main()
