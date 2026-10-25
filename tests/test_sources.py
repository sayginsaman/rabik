"""Source chips: helper commands note the meetings and facts an answer read in the ask's folder, the answer shows up to
four as chips, and a chip opens its meeting, day, page, person or fact. The model can't add one."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.meeting, brain.memory, brain.sources
from tests import native_source, scratch_dir

ROOT = Path(__file__).resolve().parents[1]


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        own = patch.object(brain.memory, 'ME_FILE', str(self.root / 'me.json')); own.start(); self.addCleanup(own.stop)   # About you, this test's own
        self.ask = self.root / 'ask'; self.ask.mkdir()

    def in_ask(self, box=True):
        return patch.dict(os.environ, {'RABIK_ASK': str(self.ask), 'RABIK_UI': '1' if box else '0'})

    def test_notes_only_inside_an_ask_and_the_answer_shows_four_distinct_once(self):
        with patch.dict(os.environ, {'RABIK_ASK': ''}): brain.sources.source_note('meeting', 'm0', 'Nowhere')
        self.assertFalse((self.ask / 'sources.jsonl').exists())
        with self.in_ask():
            for i in (1, 2, 1, 3, 4, 5): brain.sources.source_note('meeting', f'm{i}', f'Sync {i}')
            brain.sources.source_note('secret', 'x', 'Not a kind')
            with patch('sys.stdout', new_callable=io.StringIO) as out: picked = brain.sources.source_report()
        self.assertEqual([r['id'] for r in picked], ['m1', 'm2', 'm3', 'm4'])
        self.assertTrue(out.getvalue().startswith('⌖ '))
        self.assertEqual(json.loads(out.getvalue()[2:])[0], {'kind': 'meeting', 'id': 'm1', 'label': 'Sync 1'})
        self.assertFalse((self.ask / 'sources.jsonl').exists())   # read once
        with self.in_ask(box=False):
            brain.sources.source_note('day', '2026-10-24', 'Recap · Oct 24')
            with patch('sys.stdout', new_callable=io.StringIO) as out: brain.sources.source_report()
        self.assertEqual(out.getvalue(), '')   # a notification shows no chips

    def test_meeting_history_notes_the_meetings_it_returned(self):
        folder = self.root / 'meetings' / 'm1'; folder.mkdir(parents=True)
        (folder / 'metadata.json').write_text(json.dumps({'title': 'Pricing review', 'started': 1792929600, 'app': 'Zoom'}))
        (folder / 'events.jsonl').write_text(json.dumps({'kind': 'transcript', 'text': 'Pricing goes up in May.', 'seconds': 3}) + '\n')
        with self.in_ask():
            self.assertIn('Pricing goes up in May.', brain.meeting.meeting_history('what did we decide about pricing'))
            rows = [json.loads(line) for line in (self.ask / 'sources.jsonl').read_text().splitlines()]
        self.assertEqual([(r['kind'], r['id']) for r in rows], [('meeting', 'm1')])
        self.assertTrue(rows[0]['label'].startswith('Pricing review · '))

    def test_a_memory_search_notes_the_facts_it_found_but_a_full_listing_does_not(self):
        brain.memory.profile_add('people', 'Sam works at Acme', kind='Sam')
        with self.in_ask():
            brain.memory.memory_find('Sam'); brain.memory.memory_find('')
            rows = [json.loads(line) for line in (self.ask / 'sources.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['kind'], rows[0]['c'], rows[0]['t']), ('fact', 'people', 'Sam works at Acme'))

    def test_the_answer_reports_its_sources_and_the_app_opens_each_kind(self):
        cli, swift, box, settings = (ROOT / 'brain/cli.py').read_text(), native_source(), (ROOT / 'ui/ui.html').read_text(), (ROOT / 'ui/settings.html').read_text()
        self.assertIn('if attempt.ok: sources.source_report()', cli)
        self.assertIn('case "meeting": Rabik.settings.open(tab: "meetings", then: "showMeeting", id)', swift)
        self.assertIn('case "fact": Rabik.settings.reveal(["c": s["c"] as? String ?? "", "t": s["t"] as? String ?? ""])', swift)
        self.assertIn('if file.pathExtension == "app" || FileManager.default.isExecutableFile(atPath: id) { NSWorkspace.shared.activateFileViewerSelecting([file]) }', swift)
        self.assertIn("} else if (tag === '⌖' && turn()) { try { sourceChips(JSON.parse(s)); } catch {}", box)
        self.assertIn("showMeeting(id) { expectedMeeting = id; post({do: 'meetingOpen', id}); }", settings)


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class SourceChipsPageTests(unittest.TestCase):
    def test_chips_sit_under_the_answer_and_post_their_source(self):
        from tests.test_shelf_page import HARNESS
        harness = HARNESS.replace('cfg.userContentController.add(h, name: "agents")', 'cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")')
        harness = harness.replace('?["action"] as? String == "ready"', '?["ready"] != nil')
        script = r'''
            ui.listen(); ui.words('what did we decide'); ui.think(); ui.line('✓ Pricing goes up in May.');
            ui.line('⌖ ' + JSON.stringify([{kind: 'meeting', id: 'm1', label: 'Pricing review · Oct 23'}, {kind: 'bogus', id: 'x', label: 'No'}, {kind: 'fact', id: 'f1', label: 'People · Sam', c: 'people', t: 'Sam'}]));
            const chips = [...document.querySelectorAll('#thread .turn:last-child .srcs .src')];
            chips[0].click();
            return [chips.map(c => [c.dataset.kind, c.textContent, c.getAttribute('aria-label')]), document.querySelector('#thread .turn:last-child .a').nextElementSibling.className];'''
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'ui.html', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(harness)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), script], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(got['result'], [[['meeting', 'Pricing review · Oct 23', 'Meeting: Pricing review · Oct 23. Open'], ['fact', 'People · Sam', 'About you: People · Sam. Open']], 'srcs'])
        self.assertIn({'source': {'kind': 'meeting', 'id': 'm1', 'label': 'Pricing review · Oct 23'}}, got['posts'])


if __name__ == '__main__':
    unittest.main()
