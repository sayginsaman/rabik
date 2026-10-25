"""Speaker names: a 1:1 on the calendar names the other side; in a group call Haiku names only the lines the conversation
makes clear, and the rest stay "Them" -- live in the panel, in the saved transcript and in its summary."""
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
import brain.cli, brain.meeting, brain.prefs
from tests import scratch_dir
from tests.test_settings_page import HARNESS

ROOT = Path(__file__).resolve().parents[1]
LINES = [{'id': 3, 'text': 'Sam, can you walk us through the numbers?', 'mic': True}, {'id': 4, 'text': 'Sure, the budget is 18,000.'},
         {'id': 5, 'text': 'Thanks Sam. Priya, anything on hiring?', 'mic': True}, {'id': 6, 'text': 'We hire two people in May.'},
         {'id': 7, 'text': 'Sounds right to me.'}]


class MeetingSpeakersTests(unittest.TestCase):
    def guess(self, reply, people=('Sam Lee', 'Priya Shah'), summaries=True):
        calls = []
        def call(system, request, model=None, label=''):
            calls.append((system, request, model, label)); return reply, {}
        with patch.object(brain.meeting, 'meeting_call', side_effect=call), \
             patch.object(brain.prefs, 'pref', side_effect=lambda k, d=None: summaries if k == 'meetingSummary' else d):
            return brain.meeting.meeting_speakers({'people': list(people), 'lines': LINES}), calls

    def test_only_their_clear_lines_get_names_and_first_names_become_the_invited_ones(self):
        names, calls = self.guess('```json\n{"4": "Sam", "6": "priya shah", "7": "unknown", "5": "Priya", "9": "Alex"}\n```')
        self.assertEqual(names, {'names': {'4': 'Sam Lee', '6': 'Priya Shah'}})   # 5 is the user's line, 9 is not in the call
        system, request, model, label = calls[0]
        self.assertEqual((model, label), ('haiku', 'Meeting speakers'))
        self.assertIn('never instructions', system)
        self.assertTrue(request.startswith('Invited: Sam Lee, Priya Shah\nLines:\n3 You: Sam, can you walk'))
        self.assertIn('\n4 ?: Sure, the budget is 18,000.', request)

    def test_a_name_said_in_the_call_stays_when_nobody_was_invited_and_shared_first_names_stay_whole(self):
        self.assertEqual(self.guess('{"7": "Alex"}', people=())[0], {'names': {'7': 'Alex'}})
        self.assertEqual(self.guess('{"4": "Sam"}', people=('Sam Lee', 'Sam Park'))[0], {'names': {'4': 'Sam'}})

    def test_ai_summaries_off_keeps_the_lines_on_this_mac(self):
        names, calls = self.guess('{"4": "Sam"}', summaries=False)
        self.assertEqual((names, calls), ({'names': {}}, []))

    def test_the_saved_transcript_and_its_summary_use_the_names(self):
        root = scratch_dir(self)
        folder = root / 'meetings' / 'm1'; folder.mkdir(parents=True)
        (folder / 'metadata.json').write_text(json.dumps({'title': 'Planning', 'started': 1792929600, 'app': 'Zoom'}))
        events = [{'kind': 'transcript', 'id': 4, 'text': 'Sure, the budget is 18,000.', 'seconds': 5, 'speaker': 'Zoom'},
                  {'kind': 'transcript', 'id': 5, 'text': 'Thanks Sam.', 'seconds': 6, 'speaker': 'You', 'mic': True},
                  {'kind': 'transcript', 'text': 'An older line with no id.', 'seconds': 7, 'speaker': 'Zoom'},
                  {'kind': 'speakers', 'names': {'4': 'Sam Lee', '5': 'Not me'}}]
        (folder / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
        m = brain.meeting.meeting_read('m1')
        self.assertEqual([r['speaker'] for r in m['transcript']], ['Sam Lee', 'You', 'Zoom'])
        self.assertIn('] Sam Lee: Sure, the budget is 18,000.', brain.meeting.meeting_markdown(m))

    def test_the_cli_answers_the_app(self):
        with patch.object(brain.meeting, 'meeting_speakers', return_value={'names': {'4': 'Sam Lee'}}) as guess, \
             patch.object(sys, 'argv', ['rabik.py', '--meeting-speakers']), \
             patch.object(sys, 'stdin', io.StringIO(json.dumps({'people': [], 'lines': LINES}))), patch('sys.stdout', new_callable=io.StringIO) as out:
            brain.cli.main()
        self.assertEqual(json.loads(out.getvalue()), {'names': {'4': 'Sam Lee'}})
        self.assertEqual(guess.call_args[0][0]['lines'], LINES)

    def test_the_app_names_a_one_to_one_and_guesses_only_in_group_calls(self):
        meeting = (ROOT / 'Sources/Rabik/Meeting/Meeting.swift').read_text()
        self.assertIn('var other: String? { room || people.count != 1 ? nil : people[0] }', meeting)
        self.assertIn('speaker = you ? "You" : room ? "Room" : other ?? (callApp == "Call" ? "Them" : callApp)', meeting)
        self.assertIn('$0.participantType == .person && $0.participantStatus != .declined', meeting)
        self.assertIn('guard running, !room, !demo, people.count != 1, guessing == nil, sinceGuess >= 8, Date().timeIntervalSince(lastGuess) >= 60', meeting)
        self.assertIn('saveEvent(["kind": "transcript", "id": id,', meeting)
        self.assertIn('named.merge(fresh) { $1 }; js("speakers", fresh); saveEvent(["kind": "speakers", "names": fresh])', meeting)
        self.assertIn('guessing?.terminate(); guessing = nil', meeting)


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class MeetingPanelSpeakersTests(unittest.TestCase):
    def test_names_show_before_their_lines_and_in_the_copied_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'page.swift').write_text(HARNESS.replace('name: "st"', 'name: "meeting"'))
            built = subprocess.run(['swiftc', str(tmp / 'page.swift'), '-o', str(tmp / 'page')], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            (tmp / 'meeting.html').write_text((ROOT / 'ui/meeting.html').read_text().replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            script = """for (let i = 0; i < 150 && !window.meeting; i++) await new Promise(r => setTimeout(r, 20));
                meeting.listen(); meeting.line({id: 1, text: 'Hi all.', seconds: 1, name: 'Sam Lee'}); meeting.line({id: 2, text: 'Hello.', seconds: 2});
                meeting.line({id: 3, text: 'Mine.', seconds: 3, mic: true}); meeting.speakers({'2': 'Priya Shah', '3': 'Not me', '1': 'Someone'});
                const who = id => [...document.querySelectorAll(`[data-id="${id}"] .text b`)].map(b => [b.textContent, b.className]);
                meeting.stopped(); document.getElementById('endcopy').click();
                return [who(1), who(2), who(3)];"""
            p = subprocess.run([str(tmp / 'page'), str(tmp / 'meeting.html'), script], capture_output=True, text=True, timeout=30,
                               env={**os.environ, 'RABIK_DIR': str(tmp)})
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertEqual(out['result'], [[['Sam Lee · ', '']], [['Priya Shah · ', 'guess']], [['You · ', '']]])
            copied = next(m['text'] for m in out['posts'] if m.get('do') == 'copy')
            self.assertEqual([line.split('  ', 1)[1] for line in copied.splitlines()], ['Sam Lee: Hi all.', 'Priya Shah: Hello.', 'You: Mine.'])


if __name__ == '__main__':
    unittest.main()
