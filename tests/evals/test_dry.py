"""Dry eval harness (VM-safe): fake Claude + fake Mac, no network."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.evals.harness import run_all, run_scenario  # noqa: E402
from tests.evals.scenarios import SCENARIOS  # noqa: E402


@unittest.skipUnless(os.environ.get('ATTICUS_RUN_DRY_EVALS') == '1',
                     '15-scenario dry eval is opt-in (ATTICUS_RUN_DRY_EVALS=1)')
class DryEvalTests(unittest.TestCase):
    def test_all_dry_scenarios_pass(self):
        rows = run_all(ROOT, live=False)
        self.assertEqual(len(rows), len(SCENARIOS))
        failed = [r for r in rows if not r['ok']]
        self.assertFalse(failed, failed)


class EvalHookTests(unittest.TestCase):
    def test_sitecustomize_intercepts_child_processes(self):
        import os
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / 'state.json'
            state.write_text('{"browser": "Fixture Browser", "front_app": "Fixture Browser", "pages": {}, "log": [], "effects": []}')
            env = {**os.environ, 'ATTICUS_EVAL_STATE': str(state),
                   'PYTHONPATH': str(Path(__file__).resolve().parent) + os.pathsep + os.environ.get('PYTHONPATH', '')}
            r = subprocess.run([sys.executable, '-c', 'import subprocess,sys;sys.exit(subprocess.run(["pgrep","-xq","Fixture Browser"]).returncode)'], env=env)
        self.assertEqual(r.returncode, 0)

    def test_scenario_restores_environment_and_subprocess(self):
        import os
        import subprocess

        environment, run, popen = os.environ.copy(), subprocess.run, subprocess.Popen
        self.assertTrue(run_scenario(SCENARIOS[0], ROOT)['ok'])
        self.assertEqual(os.environ, environment)
        self.assertIs(subprocess.run, run)
        self.assertIs(subprocess.Popen, popen)
