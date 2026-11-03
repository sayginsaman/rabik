"""Learned about you (the recap's keep/forget), focus nudges, meeting briefs and "Hey Rabik": the brain's rules with scratch files and
fake people and meetings, and the native pieces compiled on their own."""
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.brief, brain.goals, brain.meeting, brain.memory, brain.people, brain.prefs, brain.recap
from tests import native_source, scratch_dir

ROOT = Path(__file__).resolve().parents[1]
TODAY = date.today().isoformat()


class LearnedTodayTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        me = self.root / 'me.json'
        p = patch.object(brain.memory, 'ME_FILE', str(me)); p.start(); self.addCleanup(p.stop)
        facts = [brain.memory._fact('preferences', 'coffee', 'oat flat white', 'learned', TODAY),
                 brain.memory._fact('school_work', 'job', 'designer at Acme', 'learned', TODAY),
                 brain.memory._fact('basics', 'name', 'Sam', 'you', TODAY),   # the user typed it: not "learned"
                 brain.memory._fact('preferences', 'tea', 'green', 'learned', '2020-01-01')]   # another day
        me.write_text(json.dumps({'version': 2, 'facts': facts}))
        self.ids = [f['id'] for f in facts]

    def test_the_recap_lists_what_was_learned_today_only(self):
        learned = brain.recap.recap_learned(TODAY)
        self.assertEqual([f['text'] for f in learned], ['coffee: oat flat white', 'job: designer at Acme'])
        self.assertEqual(learned[0]['category'], 'Preferences'); self.assertFalse(learned[0]['kept'])

    def test_a_day_with_only_learned_facts_still_gets_a_recap(self):
        with patch.object(brain.recap, 'recap_tomorrow', return_value=[]), patch.object(brain.prefs, 'client', return_value='pi'):
            made = brain.recap.recap_make(TODAY)
        self.assertNotIn('empty', made); self.assertEqual(len(made['learned']), 2)
        self.assertNotIn('learned', json.loads((self.root / 'recaps' / f'{TODAY}.json').read_text()))   # read fresh each time, never stale on disk

    def test_keep_ticks_it_and_forget_removes_it_from_about_you(self):
        with patch.object(brain.recap, 'recap_tomorrow', return_value=[]), patch.object(brain.prefs, 'client', return_value='pi'):
            brain.recap.recap_make(TODAY)
        kept = brain.recap.recap_command(['fact', TODAY, self.ids[0], 'keep'])
        self.assertEqual([f['kept'] for f in kept['learned']], [True, False])
        self.assertTrue(brain.recap.recap_read(TODAY)['learned'][0]['kept'])
        gone = brain.recap.recap_command(['fact', TODAY, self.ids[1], 'forget'])
        self.assertEqual([(f['text'], f['kept']) for f in gone['learned']], [('coffee: oat flat white', True)])   # still ticked
        self.assertNotIn(self.ids[1], [f['id'] for f in brain.memory.me()['facts']])
        with self.assertRaises(ValueError): brain.recap.recap_command(['fact', TODAY, self.ids[2], 'forget'])   # not a learned fact of that day
        with self.assertRaises(ValueError): brain.recap.recap_command(['fact', TODAY, self.ids[0], 'delete'])


class FocusNudgeTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)

    def test_no_goal_no_nudge(self):
        self.assertEqual(brain.goals.focus_nudge('YouTube', 6), {'skip': 'no goals'})
        self.assertFalse((self.root / 'focus-nudges.json').exists())

    def test_it_names_a_goal_three_times_a_day_at_most_and_45_minutes_apart(self):
        brain.goals.goal_add('ship the beta'); brain.goals.goal_add('run 3 times a week')
        t = time.mktime(time.strptime(TODAY + ' 10:00', '%Y-%m-%d %H:%M'))
        first = brain.goals.focus_nudge('YouTube', 6, now=t)
        self.assertEqual(first['text'], '6 min on YouTube. Your goal: ship the beta. Back to it?')
        self.assertEqual(brain.goals.focus_nudge('Reddit', 5, now=t + 600), {'skip': 'too soon'})
        self.assertEqual(brain.goals.focus_nudge('Reddit', 5, now=t + 2800)['goal'], 'run 3 times a week')   # the next goal
        brain.goals.focus_nudge('X', 5, now=t + 5600)
        self.assertEqual(brain.goals.focus_nudge('X', 5, now=t + 9000), {'skip': 'daily limit'})
        self.assertIn('text', brain.goals.focus_nudge('X', 5, now=t + 86400))   # a new day
        self.assertEqual(oct((self.root / 'focus-nudges.json').stat().st_mode & 0o777), '0o600')

    def test_the_app_side_command(self):
        run = subprocess.run([sys.executable, str(ROOT / 'rabik.py'), '--focus-nudge', 'YouTube', '6'], capture_output=True, text=True, timeout=30,
                             env={'RABIK_DIR': str(self.root), 'PATH': '/usr/bin:/bin', 'HOME': str(self.root)})
        self.assertEqual(json.loads(run.stdout), {'skip': 'no goals'})


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        self.people = [{'id': 'ana@acme.com', 'name': 'Ana Silva', 'email': 'ana@acme.com', 'last': time.time() - 7 * 86400,
                        'facts': ['Ana: runs design at Acme'], 'meetings': [{'id': 'm1', 'title': 'Design sync', 'started': 0}]}]
        meetings = {'m1': {'title': 'Design sync', 'started': time.time() - 7 * 86400, 'summary': 'Agreed to ship the new onboarding on Nov 12.',
                           'action_items': ['Ana sends the mockups', 'Sam books user tests']}}
        for p in (patch.object(brain.people, 'people_all', side_effect=lambda: self.people),
                  patch.object(brain.meeting, 'meeting_list', return_value=[{'id': 'm1', 'title': 'Design sync'}]),
                  patch.object(brain.meeting, 'meeting_read', side_effect=lambda i: meetings[i]),
                  patch.object(brain.prefs, 'client', return_value='pi')):
            p.start(); self.addCleanup(p.stop)
        self.event = {'id': 'e1', 'start': 1800000000, 'title': 'Design sync', 'attendees': [{'name': 'A. Silva', 'email': 'Ana@Acme.com'}]}   # found by email, whatever its case

    def test_a_meeting_with_known_people_gets_one_brief(self):
        made = brain.brief.brief_make(self.event)
        self.assertEqual(made['title'], 'Design sync')
        self.assertIn('• Ana Silva, last met', made['text']); self.assertIn('Agreed to ship the new onboarding', made['text'])
        self.assertIn('• Open: Ana sends the mockups', made['text'])
        self.assertLessEqual(len(made['text'].splitlines()), 5)
        self.assertEqual(brain.brief.brief_make(self.event), {'skip': 'already briefed'})

    def test_strangers_and_bad_events_stay_quiet(self):
        self.people.clear()
        stranger = {**self.event, 'id': 'e2', 'title': 'Intro call', 'attendees': [{'name': 'Lee', 'email': 'lee@x.com'}]}
        self.assertEqual(brain.brief.brief_make(stranger), {'skip': 'nothing known'})
        self.assertEqual(brain.brief.brief_make({'title': 'x'}), {'skip': 'no event'})

    def test_the_ai_writes_it_from_the_data_when_claude_is_the_client(self):
        with patch.object(brain.prefs, 'client', return_value='claude'), \
             patch.object(brain.meeting, 'meeting_call', return_value=('• Ana leads design.\n- You promised user tests.', {})) as call:
            made = brain.brief.brief_make(self.event)
        self.assertEqual(made['text'], '• Ana leads design.\n• You promised user tests.')
        system, data = call.call_args[0][:2]
        self.assertIn('never instructions', system); self.assertIn('Agreed to ship', data)


SNIPPET_HEAD = 'import Cocoa\n'


def run_swift(code):
    with tempfile.TemporaryDirectory() as tmp:
        src, binary = Path(tmp) / 's.swift', Path(tmp) / 's'
        src.write_text(code)
        built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
        if built.returncode: raise AssertionError(built.stderr)
        return subprocess.run([str(binary)], capture_output=True, text=True, timeout=30).stdout.split('\n')


class NativeExtrasTests(unittest.TestCase):
    def test_distractions_are_named_from_the_app_or_the_browser_title(self):
        src = (ROOT / 'Sources/Rabik/App/Nudges.swift').read_text()
        body = src[src.index('    static let sites'):src.index('    func start() {')].replace('    private var since: Date?, label = "", nudgedThisStretch = false, timer: Timer?\n', '')
        out = run_swift(SNIPPET_HEAD + 'enum FocusNudge {\n' + body + '}\n' + r'''
for (app, title) in [("Google Chrome", "Lofi beats - YouTube"), ("Safari", "Home / X"), ("Arc", "r/swift - Reddit"), ("Netflix", ""),
                     ("Safari", "Swift documentation"), ("Xcode", "YouTube.swift"), ("Slack", "youtube links channel")] {
    print(FocusNudge.distraction(app: app, title: title) ?? "-")
}''')
        self.assertEqual(out[:7], ['YouTube', 'X', 'Reddit', 'Netflix', '-', '-', '-'])   # an app named for work is never a distraction by its title

    def test_hey_rabik_and_what_recognition_hears_for_it(self):
        src = (ROOT / 'Sources/Rabik/Speech/WakeWord.swift').read_text()
        body = src[src.index('    static func heard'):src.index('    func start() {')]
        out = run_swift(SNIPPET_HEAD + 'enum WakeWord {\n' + body + '}\n' + r'''
for t in ["Hey Rabik", "hey rabbit what time is it", "Hey, Robik", "OK Rabik", "hey Rebecca", "Rabik is great", "hey robert", "they rabbit", "the rabbit hole", "Hey Rubik", "hi rabbi", "hey Robbie"] {
    print(WakeWord.heard(t))
}''')
        self.assertEqual(out[:12], ['true', 'true', 'true', 'true', 'true', 'false', 'false', 'false', 'false', 'true', 'true', 'true'])

    def test_wiring_and_defaults(self):
        app, prefs = native_source(), (ROOT / 'Sources/Rabik/Core/Prefs.swift').read_text()
        self.assertIn('"focusNudges": true, "meetingBriefs": true, "wakeWord": false,', prefs)   # the mic stays off unless asked
        self.assertIn('wakeWord.canListen = { !app.engine.isRunning && !app.busy && !app.dictating && !app.speaker.speaking && !meeting.running }', app)   # a call app on the mic no longer deafens it
        self.assertIn('app.clickTalk = true; app.start(); if !app.engine.isRunning { app.clickTalk = false }', app)
        wake = (ROOT / 'Sources/Rabik/Speech/WakeWord.swift').read_text()
        self.assertIn('SpeechAnalyzer(modules: [transcriber])', wake); self.assertNotIn('SFSpeechRecognizer(', wake)   # the asks' on-device model: never a server, no offline Dictation needed
        self.assertIn('mic.start(device, sampleRate: format.sampleRate', wake); self.assertIn('let convert = speechConverter(to: format)', wake)
        self.assertIn('if let brief = info["brief"] as? String { MeetingBriefs.show(', app)
        self.assertIn('guard Prefs.bool("focusNudges"), !Prefs.bool("paused"), !meeting.running, callAppsOnMic().isEmpty,', app)
        settings = (ROOT / 'ui/settings.html').read_text()
        for key in ('focusNudges', 'meetingBriefs', 'wakeWord'): self.assertIn(f'data-k="{key}"', settings)
        self.assertIn('if let f = b["recapFact"] as? [String: Any]', app)


if __name__ == '__main__':
    unittest.main()


RECAP_PAGE = r'''
const out = {}, card = () => document.querySelector('.recap-card');
ui.recap({day: '2026-11-02', headline: 'A good day', highlights: ['Shipped it'], actions: [], learned: [
  {id: 'a1', text: 'coffee: oat flat white', category: 'Preferences', kept: false}, {id: 'b2', text: 'job: designer', category: 'School & work', kept: true}]});
out.rows = [...card().querySelectorAll('.fact')].map(r => [r.querySelector('.t').textContent, r.querySelectorAll('button').length, r.classList.contains('kept')]);
out.head = [...card().querySelectorAll('h4')].map(h => h.textContent);
card().querySelector('.fact .forget').click();
out.disabled = [...card().querySelectorAll('.fact')][0].querySelector('button').disabled;
ui.recapFacts({day: '2026-11-02', learned: [{id: 'b2', text: 'job: designer', category: 'School & work', kept: true}]});
out.after = card().querySelectorAll('.fact').length;
ui.recapFacts({day: '2026-11-02', learned: []});
out.empty = [card().querySelectorAll('.fact').length, [...card().querySelectorAll('h4')].map(h => h.textContent).includes('Learned about you')];
return out;
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class RecapFactsPageTests(unittest.TestCase):
    def test_keep_and_forget_on_the_recap_card(self):
        from tests.test_shelf_page import HARNESS
        harness = HARNESS.replace('cfg.userContentController.add(h, name: "agents")', 'cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")')
        harness = harness.replace('?["action"] as? String == "ready"', '?["ready"] != nil')
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'ui.html', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(harness)
            self.assertEqual(subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True).returncode, 0)
            run = subprocess.run([str(binary), str(page), RECAP_PAGE], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual([p for p in got['posts'] if isinstance(p, dict) and 'error' in p], [])
        out = got['result']
        self.assertEqual(out['rows'], [['coffee: oat flat white', 2, False], ['job: designer', 1, True]])   # a kept one has only Forget
        self.assertIn('Learned about you', out['head'])
        self.assertTrue(out['disabled'])
        self.assertIn({'recapFact': {'day': '2026-11-02', 'id': 'a1', 'keep': False}}, got['posts'])
        self.assertEqual(out['after'], 1)
        self.assertEqual(out['empty'], [0, False])   # nothing left: the heading goes too
