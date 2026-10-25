"""rabik.py --mcp: Rabik's memory as a read-only MCP server on stdio for Claude Code and Claude Desktop."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.goals, brain.mcp, brain.memory, brain.prefs, brain.storage
from tests import scratch_dir

ROOT = Path(__file__).resolve().parents[1]


def call(name, **args):
    return brain.mcp.mcp_reply({'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}})['result']


class McpTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        own = patch.object(brain.memory, 'ME_FILE', str(self.root / 'me.json')); own.start(); self.addCleanup(own.stop)   # About you, this test's own
        folder = self.root / 'meetings' / 'm1'; folder.mkdir(parents=True)
        (folder / 'metadata.json').write_text(json.dumps({'title': 'Pricing review', 'started': 1792929600, 'app': 'Zoom'}))
        events = [{'kind': 'transcript', 'text': 'The secret budget is 18,000.', 'seconds': 5, 'speaker': 'Sam Lee'},
                  {'kind': 'summary', 'text': 'Prices go up in May.', 'action_items': ['Sam sends the deck'], 'revision': [1, None, 5.0]}]
        (folder / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))

    def test_handshake_lists_read_only_tools_and_answers_errors(self):
        init = brain.mcp.mcp_reply({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26', 'capabilities': {}}})['result']
        self.assertEqual((init['protocolVersion'], init['serverInfo']['name'], init['capabilities']), ('2025-03-26', 'rabik', {'tools': {'listChanged': False}}))
        self.assertEqual(brain.mcp.mcp_reply({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '1999-01-01'}})['result']['protocolVersion'], '2025-06-18')
        self.assertIsNone(brain.mcp.mcp_reply({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
        tools = brain.mcp.mcp_reply({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})['result']['tools']
        self.assertEqual([t['name'] for t in tools], ['search_memory', 'list_meetings', 'read_meeting', 'people', 'goals', 'daily_recap', 'search_activity'])
        self.assertTrue(all(t['annotations']['readOnlyHint'] and not t['annotations']['destructiveHint'] for t in tools))
        self.assertEqual(brain.mcp.mcp_reply({'jsonrpc': '2.0', 'id': 3, 'method': 'resources/list'})['error']['code'], -32601)
        self.assertEqual(brain.mcp.mcp_reply({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'forget_everything'}})['error']['code'], -32602)

    def test_tools_read_memory_meetings_goals_and_recaps(self):
        brain.memory.profile_add('people', 'works at Acme', kind='Sam Lee')
        brain.goals.goal_add('Ship the beta')
        self.assertIn('Sam Lee: works at Acme', call('search_memory', query='Sam')['content'][0]['text'])
        self.assertTrue(call('list_meetings', query='pricing')['content'][0]['text'].startswith('m1 · '))
        self.assertIn('The secret budget is 18,000.', call('read_meeting', id='m1')['content'][0]['text'])
        self.assertIn('Sam Lee', call('people')['content'][0]['text'])
        self.assertEqual(call('goals')['content'][0]['text'], '- Ship the beta')
        (self.root / 'recaps').mkdir()
        brain.storage.private_json(str(self.root / 'recaps' / '2026-10-24.json'), {'day': '2026-10-24', 'headline': 'Shipped it', 'highlights': ['Tests pass'], 'focus': ['App.swift · Xcode · 40 min']})
        day = call('daily_recap', date='2026-10-24')['content'][0]['text']
        self.assertIn('Shipped it', day); self.assertIn('Most time on:\n- App.swift · Xcode · 40 min', day)
        self.assertTrue(call('daily_recap', date='yesterday-ish')['isError'])
        self.assertTrue(call('read_meeting', id='../../etc')['isError'])
        self.assertIn('Activity history is off', call('search_activity', query='pricing')['content'][0]['text'])

    def test_ai_summaries_off_keeps_transcripts_private(self):
        with patch.object(brain.prefs, 'pref', side_effect=lambda k, d=None: False if k == 'meetingSummary' else d):
            text = call('read_meeting', id='m1')['content'][0]['text']
        self.assertIn('Prices go up in May.', text)
        self.assertNotIn('secret budget', text)

    def test_stdout_carries_only_json_rpc(self):
        lines = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}}, {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                 {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'goals', 'arguments': {}}}]
        out = io.StringIO(); brain.mcp.mcp_serve(io.StringIO('\n'.join(json.dumps(m) for m in lines) + '\nnot json\n'), out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r.get('id') for r in replies], [1, 2, None])
        self.assertEqual(replies[2]['error']['code'], -32700)
        p = subprocess.run([sys.executable, str(ROOT / 'rabik.py'), '--mcp'], input=json.dumps(lines[0]) + '\n', capture_output=True, text=True, timeout=30,
                           env={**os.environ, 'RABIK_DIR': str(self.root)})
        self.assertEqual(json.loads(p.stdout)['result']['serverInfo']['name'], 'rabik')

    def test_adding_to_claude_code_runs_claude_mcp_add_once(self):
        ran = []
        def fake(args, **kw):
            ran.append(args[1:]); return subprocess.CompletedProcess(args, 0 if args[2] == 'add' else 1, '', '')
        with patch.object(brain.mcp.subprocess, 'run', side_effect=fake), patch.dict(os.environ, {'RABIK_CLAUDE': '/fake/claude'}):
            self.assertEqual(brain.mcp.mcp_install(check=True), {'added': False})
            self.assertEqual(brain.mcp.mcp_install(), {'added': True})
        self.assertEqual(ran[-1], ['mcp', 'add', '--scope', 'user', 'rabik', '--', '/bin/sh', brain.mcp.paths.ME, '--mcp'])
        settings = (ROOT / 'Sources/Rabik/Settings/SettingsWindow.swift').read_text()
        self.assertIn('let arg = b["do"] as? String == "mcpAdd" ? "--mcp-install" : "--mcp-status"', settings)
        self.assertIn('"args": [dir + "/rabik.py", "--mcp"]', settings)


if __name__ == '__main__':
    unittest.main()
