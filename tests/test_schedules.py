"""Schedules: one-time tasks (with what happens when the Mac slept through them), chosen weekdays, labels, the command the AI
uses, and unattended runs the user OKs once when they set them up."""
import json
import os
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.agents, brain.paths, brain.policy, brain.prefs, brain.prompts, brain.routine, brain.storage


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        self.env = patch.dict(os.environ, {'RABIK_DIR': self.root.name}); self.env.start(); self.addCleanup(self.env.stop)
        self.code = patch.multiple(brain.paths, DIR=self.root.name, HOME=self.root.name, PREFS=str(Path(self.root.name) / 'settings.json'))
        self.code.start(); self.addCleanup(self.code.stop)
        Path(brain.paths.PREFS).write_text('{}')
        self.late = 'skip'
        pref = patch.object(brain.prefs, 'pref', side_effect=lambda k, d=None: self.late if k == 'routineLate' else d); pref.start(); self.addCleanup(pref.stop)
        self.notes = []
        note = patch.object(brain.routine, 'routine_notify', side_effect=self.notes.append); note.start(); self.addCleanup(note.stop)

    def at(self, day, hour, minute):   # Oct 19, 2026 is a Monday
        return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))

    def job(self, row):
        with open(brain.routine.routine_job_path(row['id']), 'rb') as f: return plistlib.load(f)

    def test_chosen_weekdays_run_only_on_those_days(self):
        row = brain.routine.routine_add('time', '09:00', 'Summarize my calendar', now=self.at(19, 7, 0), days='thu,mon')
        self.assertEqual((row['days'], row['label']), ('mon,thu', 'Mondays and Thursdays at 9:00 AM'))
        self.assertEqual([r['Weekday'] for r in self.job(row)['StartCalendarInterval']], [1, 4])   # launchd: Sunday 0, Monday 1
        self.assertTrue(brain.routine.routine_fire(row['id'], self.at(19, 9, 0)))   # Monday
        self.assertFalse(brain.routine.routine_fire(row['id'], self.at(20, 9, 0)))   # Tuesday
        self.assertTrue(brain.routine.routine_fire(row['id'], self.at(22, 9, 1)))   # Thursday
        weekend = brain.routine.routine_add('time', '10:30', 'Plan the week', now=self.at(19, 7, 0), days='weekends')
        self.assertEqual([r['Weekday'] for r in self.job(weekend)['StartCalendarInterval']], [6, 0])
        self.assertEqual(weekend['label'], 'Weekends at 10:30 AM')
        with self.assertRaises(ValueError): brain.routine.routine_add('time', '09:00', 'x', days='mon,funday')

    def test_a_one_time_task_runs_once_at_its_moment(self):
        row = brain.routine.routine_add('once', '20:00', 'Open Discord and send Ali: on my way', now=self.at(19, 15, 0), date='today')
        self.assertEqual((row['date'], row['label']), ('2026-10-19', 'Once on Mon, Oct 19 at 8:00 PM'))
        self.assertEqual(self.job(row)['StartCalendarInterval'], {'Month': 10, 'Day': 19, 'Hour': 20, 'Minute': 0})
        self.assertFalse(brain.routine.routine_fire(row['id'], self.at(19, 19, 58)))
        self.assertTrue(brain.routine.routine_fire(row['id'], self.at(19, 20, 0)))
        self.assertFalse(brain.routine.routine_fire(row['id'], self.at(19, 20, 1)))   # never twice
        self.assertEqual(brain.routine.routine_add('once', '08:00', 'x', now=self.at(19, 15, 0), date='tomorrow')['date'], '2026-10-20')
        for date, when in (('today', '14:00'), ('2026-02-30', '10:00'), ('2028-01-01', '10:00'), ('next week', '10:00')):
            with self.assertRaises(ValueError): brain.routine.routine_add('once', when, 'x', now=self.at(19, 15, 0), date=date)

    def test_a_slept_through_task_is_skipped_and_reported_unless_settings_say_otherwise(self):
        row = brain.routine.routine_add('once', '20:00', 'Send the report', now=self.at(19, 15, 0), date='today')
        self.assertFalse(brain.routine.routine_fire(row['id'], self.at(19, 20, 40)))   # 40 min late, default: skip
        self.assertEqual(brain.routine.routines(), [])
        self.assertTrue(self.notes and self.notes[0].startswith('Missed: Send the report'))
        self.late = '2h'
        late = brain.routine.routine_add('once', '20:00', 'Send it late', now=self.at(19, 15, 0), date='today')
        self.assertTrue(brain.routine.routine_fire(late['id'], self.at(19, 21, 30)))
        self.late = 'always'
        always = brain.routine.routine_add('once', '20:00', 'Whenever', now=self.at(19, 15, 0), date='today')
        self.assertTrue(brain.routine.routine_fire(always['id'], self.at(21, 9, 0)))

    def test_the_command_reads_days_dates_and_unattended(self):
        with patch.object(brain.routine.time, 'time', return_value=self.at(19, 15, 0)):
            said = brain.routine.routine_command(['add', 'time', '09:00', 'Monday,Thursday', 'Summarize my calendar', 'balanced'])
            self.assertEqual(said, 'Scheduled Mondays and Thursdays at 9:00 AM: Summarize my calendar')
            said = brain.routine.routine_command(['add', 'once', 'today', '20:00', 'Open Discord and send Ali: on my way', '--unattended'])
        self.assertEqual(said, 'Scheduled Once on Mon, Oct 19 at 8:00 PM · runs without asking: Open Discord and send Ali: on my way')
        self.assertTrue(brain.routine.routines()[-1]['unattended'])
        self.assertIn('add once <YYYY-MM-DD|today|tomorrow> HH:MM', brain.routine.routine_command(['--help']))
        with self.assertRaises(ValueError) as error: brain.routine.routine_command(['add', 'sometime'])
        self.assertIn('--unattended', str(error.exception))   # a wrong call gets the usage back

    def test_only_an_unattended_schedule_asks_and_its_run_needs_no_card(self):
        me = brain.paths.ROUTINE
        self.assertEqual(brain.policy.risky(f'{me} add once today 20:00 "open Discord and send Ali: hi"'), '')   # nothing happens now
        self.assertEqual(brain.policy.risky(f'{me} add once today 20:00 "open Discord and send Ali: hi" --unattended'), 'Run this later without asking?')
        self.assertEqual(brain.policy.risky(f'{brain.paths.WATCH} press "ChatGPT" "Allow"'), 'Click this whenever it appears?')
        ask = Path(self.root.name) / 'agents' / ('a' * 32); ask.mkdir(parents=True)
        gate = Path(brain.paths.agent_gate_dir(str(ask))); gate.mkdir(parents=True)
        (gate / 'allow-task').write_text(json.dumps(['*']))
        with patch.dict(os.environ, {'RABIK_ASK': str(ask)}):
            self.assertTrue(brain.policy.task_allowed('Bash: send'))
            self.assertTrue(brain.policy.task_allowed('hands click'))
            self.assertFalse(brain.policy.task_allowed(''))

    def test_an_unattended_one_time_routine_starts_preapproved_and_is_then_gone(self):
        routine = brain.routine.routine_add('once', '20:00', 'Open Discord and send Ali: on my way', now=self.at(19, 15, 0), date='today', unattended=True)
        events = []
        def launch(row):
            return subprocess.Popen([sys.executable, '-u', '-c', 'import sys,time\nfor line in sys.stdin: time.sleep(.01)'],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True, cwd=row['directory'])
        manager = brain.agents.Agents(emit=events.append, launch=launch); self.addCleanup(manager.close)
        manager.command({'action': 'routine', 'id': routine['id']})
        agent = next(row for row in manager.rows.values() if row.get('routine') == routine['id'])
        self.assertEqual(brain.routine.routines(), [])   # a one-time routine is done once it starts
        self.assertIn('approved its actions when they scheduled it', agent['context'])
        manager.command({'action': 'start', 'id': agent['id'], 'text': agent['brief']})
        allowed = json.loads((Path(brain.paths.agent_gate_dir(agent['directory'])) / 'allow-task').read_text())
        self.assertEqual(allowed, ['*'])

    def test_schedule_words_bring_the_usage_and_the_prompt_stays_lean(self):
        for ask in ('bugün saat 8 de discorda gir Ali ye mesaj at', 'her pazartesi ve perşembe 9da takvimimi özetle',
                    'if ChatGPT asks for permission, allow it', 'every weekday at 8 summarize my inbox', 'chatgpt izin isterse onayla'):
            self.assertIn('--unattended', brain.prompts.schedule_help(ask), ask)
        for ask in ('open Spotify', "what's on my screen?", 'move this window left'):
            self.assertEqual(brain.prompts.schedule_help(ask), '', ask)
        self.assertIn('{0} --help, {1} --help'.format(brain.paths.ROUTINE, brain.paths.WATCH), brain.prompts.SYSTEM)


if __name__ == '__main__':
    unittest.main()
