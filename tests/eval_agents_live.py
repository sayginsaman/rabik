"""Opt-in, read-only account eval: run ONLY with rabik-vm-tests/run.sh <repo> tests.eval_agents_live -v."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest

import rabik


class LiveResearchTests(unittest.TestCase):
    def test_real_research_agent_returns_products_and_sources(self):
        claude = shutil.which('claude') or os.path.expanduser('~/.local/bin/claude')
        auth = subprocess.run([claude, 'auth', 'status', '--json'], capture_output=True, text=True, timeout=15)
        if not json.loads(auth.stdout).get('loggedIn'):
            self.skipTest('Sign in to Claude inside rabik-test, then rerun this opt-in eval.')
        rabik.private_json(rabik.PREFS, {'safe': True, 'agentUserTools': True})
        os.environ['RABIK_CLAUDE'] = claude
        manager = rabik.Agents(emit=lambda _: None)
        self.addCleanup(manager.close)
        request = 'Research the best products on Amazon for my home'
        row = manager.prepare({'title': 'Home product research', 'brief': request,
                               'context': 'Read-only evaluation. No purchases, messages, account or file changes. No personal home details are available; state assumptions.'})
        manager.start(row['id']); started = time.monotonic()
        while row['status'] not in ('done', 'failed', 'stopped') and time.monotonic() - started < 600:
            manager.tick()
            if row.get('question'):
                question = row['question']
                manager.command({'action': 'answer', 'id': row['id'], 'question': question.get('_a'), 'answer': 'n'})
            time.sleep(.15)
        evidence = {k: row.get(k) for k in ('status', 'step', 'result', 'summary', 'links', 'cost', 'usage', 'sources', 'timeline')}
        evidence['seconds'] = round(time.monotonic() - started, 3)
        output = Path(__file__).resolve().parents[1] / 'test-artifacts' / 'live-research.json'
        output.parent.mkdir(exist_ok=True); rabik.private_json(str(output), evidence)
        print(f'Live agent: {row["status"]}, {evidence["seconds"]} s; evidence: {output}', flush=True)
        self.assertEqual(row['status'], 'done', row.get('step'))
        self.assertGreaterEqual(len(rabik.agent_sources(row.get('result', '') + '\n' + '\n'.join(row.get('links', [])))), 3,
                                'Expected multiple actual product/source URLs; inspect live-research.json for product quality.')
        self.assertTrue(any(e.get('tool') for e in row['timeline']), 'Eval must execute real tools, not only classify the request.')

