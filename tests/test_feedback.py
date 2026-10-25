"""Feedback privacy and instant routing; no browser or AI calls."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import urllib.parse
from unittest.mock import patch
import platform
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import rabik
import brain.cli, brain.clients, brain.hands, brain.instant, brain.interaction, brain.paths, brain.screen, brain.support
from tests import scratch_dir


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        for p in [patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Mac14,5\n')),
                  patch.object(platform, 'mac_ver', return_value=('26.0', (), ''))]:
            p.start(); self.addCleanup(p.stop)
        (self.root / 'log.jsonl').write_text(json.dumps({'task': 'Private ask /Users/person/name', 'reply': 'PRIVATE ANSWER', 'ran': ['PRIVATE COMMAND'], 'steps': ['Searching the web: PRIVATE QUERY']})+'\n'+json.dumps({'task': 'report feedback'})+'\n')

    def test_default_contains_only_template_and_whitelisted_environment(self):
        report = brain.support.feedback({'version': '9429210'})
        self.assertFalse(report['include'])
        self.assertIn('Mac model: Mac14,5', report['body'])
        self.assertIn('Version / commit: 9429210', report['body'])
        self.assertIn('Version: ' + brain.paths.APP_VERSION, report['body']); self.assertIn('Routing: ', report['body'])
        self.assertNotIn('Install ID', report['body'])   # the issue is public: never link it to the anonymous stats
        for secret in ['Private ask', '/Users', 'PRIVATE ANSWER', 'PRIVATE COMMAND', str(self.root)]:
            self.assertNotIn(secret, report['body']); self.assertNotIn(urllib.parse.quote(secret), report['url'])
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(report['url']).query)
        self.assertEqual(query['body'], [report['body']])
        self.assertIn('What happened', report['body']); self.assertIn('What you expected', report['body'])

    def test_opt_in_shows_exact_previous_ask_only(self):
        report = brain.support.feedback({'include': True})
        self.assertIn('Private ask /Users/person/name', report['body'])
        self.assertNotIn('PRIVATE QUERY', report['body'])   # step names quote screen content and searches
        self.assertNotIn('PRIVATE ANSWER', report['body']); self.assertNotIn('PRIVATE COMMAND', report['body'])
        self.assertNotIn('report feedback', report['body'])
        self.assertTrue(report['include'])

    def test_feedback_always_waits_for_confirmation_and_skips_ai(self):
        for request in ('report feedback', 'report a bug'):
            with patch('sys.argv', ['rabik.py', request]), patch.object(brain.clients, 'start_claude') as ai, patch.object(brain.interaction, 'wait_commit', return_value=True) as gate, patch('sys.stdout', new_callable=io.StringIO) as out, patch.object(brain.screen, 'look', return_value=[]), patch.object(brain.hands, 'hands_map', return_value=None):
                brain.cli.main()
                ai.assert_not_called(); gate.assert_called_once()
                self.assertIn('! feedback', out.getvalue())
                self.assertIn('Review your feedback', out.getvalue())
            with patch.dict(os.environ, {'RABIK_LIVE': '1'}, clear=True), patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertIsNone(brain.instant.fast(request).reply); self.assertEqual(out.getvalue(), '')

    def test_a_request_about_keys_is_an_ordinary_ask(self):
        # Atticus kept an unused $5 Gumroad check on every ask: "key bindings" went to Gumroad's license API and got
        # "That key did not work" back. Rabik has no license check, so nothing but the model sees such a request.
        for name in ('licensed', 'activate', 'GUMROAD_PRODUCT', 'BUY', 'KEY_FILE'):
            self.assertFalse(hasattr(rabik, name), name)
        modules = Path(brain.paths.ME).parent / 'brain'
        for path in [Path(brain.paths.ME), *sorted(modules.glob('*.py'))]:   # the brain's code is rabik.py and brain/
            self.assertNotIn('gumroad', path.read_text(encoding='utf-8').lower(), path.name)
