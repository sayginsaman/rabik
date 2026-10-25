"""The daily recap (brain/recap.py): what one AI call reads, what of its answer is kept, when it is made, and adding the user's
picks to Reminders once each. A fake model, calendar and Reminders; real recap and meeting files in a scratch folder."""
from datetime import date, datetime, timedelta
import io
import json
import os
from pathlib import Path
import stat
import sys
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.agents, brain.calendar, brain.interaction, brain.macos, brain.meeting, brain.policy, brain.prefs, brain.recap
from tests import scratch_dir

DAY = '2026-10-25'
NOON = datetime(2026, 10, 25, 12).timestamp()


class RecapTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        self.prefs = {}
        self.calls, self.added = [], []
        def backend(data):
            if data['action'] == 'list': return {'events': [{'title': 'Design review', 'start': '2026-10-26T10:00:00+03:00', 'allDay': False}]}
            if data['action'] == 'addReminders':
                self.calls.append(data)
                if self.prefs.get('_need'): return {'need': 'reminders'}
                ids = [f'r{len(self.added) + i}' for i in range(len(data['items']))]; self.added += ids
                return {'added': ids, 'list': 'Reminders', 'fellBack': False}
            raise AssertionError(data)
        self.ai = patch.object(brain.meeting, 'meeting_call', return_value=('{}', {})); self.model = self.ai.start(); self.addCleanup(self.ai.stop)
        for p in (patch.object(brain.calendar, 'calendar_backend', side_effect=backend),
                  patch.object(brain.prefs, 'pref', side_effect=lambda k, d: self.prefs.get(k, d)),
                  patch.object(brain.agents, 'agent_history', side_effect=lambda full=True: self.agents)):
            p.start(); self.addCleanup(p.stop)
        self.agents = []

    def log(self, *rows):
        with open(self.root / 'log.jsonl', 'a') as f:
            for row in rows: f.write(json.dumps(row) + '\n')

    def meeting(self, ident='m1', actions=('Saygin sends the deck by Friday', 'Book the room'), started=NOON, summary='We agreed to ship on Monday.'):
        folder = self.root / 'meetings' / ident; folder.mkdir(parents=True)
        (folder / 'metadata.json').write_text(json.dumps({'title': 'Weekly sync', 'started': started, 'app': 'Zoom'}))
        events = [{'kind': 'transcript', 'text': 'Let us ship on Monday.', 'seconds': 5},
                  {'kind': 'summary', 'text': summary, 'action_items': list(actions), 'revision': [1, None, 5.0]}]
        (folder / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
        return ident

    def answer(self, data):
        self.model.return_value = (json.dumps(data), {})

    def test_an_empty_day_makes_no_call_no_file_and_no_notice(self):
        self.log({'at': f'{DAY} 09:00:00', 'task': 'open spotify', 'reply': 'Opened Spotify.', 'status': 'completed', 'path': 'instant'},
                 {'at': '2026-10-24 09:00:00', 'task': 'yesterday', 'reply': 'Done.', 'status': 'completed', 'path': 'model'})
        self.assertEqual(brain.recap.recap_make(DAY), {'day': DAY, 'empty': True})
        self.model.assert_not_called()
        self.assertFalse((self.root / 'recaps' / f'{DAY}.json').exists())

    def test_inputs_are_today_only_and_bounded(self):
        self.log({'at': f'{DAY} 09:00:00', 'task': 'open spotify', 'reply': 'Opened Spotify.', 'status': 'completed', 'path': 'instant'},
                 {'at': f'{DAY} 10:00:00', 'task': 'Summarize this PDF ' + 'x' * 400, 'reply': 'It says y.', 'status': 'completed', 'path': 'model'},
                 {'at': f'{DAY} 10:05:00', 'task': 'Meeting Copilot', 'reply': '', 'status': 'completed'},   # a logged label, not an ask
                 {'at': f'{DAY} 10:06:00', 'task': 'broken', 'reply': 'x', 'status': 'failed'},
                 {'at': '2026-10-24 10:00:00', 'task': 'old', 'reply': 'x', 'status': 'completed'})
        self.agents = [{'id': 'a' * 32, 'status': 'done', 'ended': NOON, 'title': 'USB-C hubs', 'summary': 'Three hubs under $30.', 'changes': '', 'links': []},
                       {'id': 'b' * 32, 'status': 'done', 'ended': NOON - 86400, 'title': 'Yesterday'},
                       {'id': 'c' * 32, 'status': 'running', 'title': 'Still going'}]
        self.meeting(); self.meeting('m0', started=NOON - 86400)
        inputs = brain.recap.recap_inputs(DAY)
        self.assertEqual([a['asked'][:19] for a in inputs['asks']], ['Summarize this PDF '])
        self.assertEqual(len(inputs['asks'][0]['asked']), 200)
        self.assertEqual(inputs['instant'], 1)
        self.assertEqual([a['id'] for a in inputs['agents']], ['agent:' + 'a' * 32])
        self.assertEqual([m['id'] for m in inputs['meetings']], ['meeting:m1'])
        self.assertEqual(inputs['meetings'][0]['actions'], ['Saygin sends the deck by Friday', 'Book the room'])
        self.assertEqual(inputs['tomorrow'], [{'title': 'Design review', 'at': '10:00'}])
        span = brain.calendar.calendar_backend.call_args_list[0].args[0]
        self.assertEqual((span['from'][:10], span['to'][:10]), ('2026-10-26', '2026-10-27'))

    def test_the_model_keeps_only_what_the_data_backs(self):
        self.meeting(); self.agents = [{'id': 'a' * 32, 'status': 'done', 'ended': NOON, 'title': 'Hubs', 'summary': 'Found three hubs.', 'changes': ''}]
        self.answer({'headline': 'A sync and a hub search.', 'highlights': ['Agreed to ship Monday', 7], 'decisions': ['Ship on Monday'],
                     'actions': [{'text': 'Send the deck', 'from': 'meeting:m1', 'due': '2026-10-31'},       # "by Friday": kept
                                 {'text': 'Order a hub', 'from': 'agent:' + 'a' * 32, 'due': '2026-10-28'},  # no date in its source: dropped
                                 {'text': 'Invented', 'from': 'meeting:zz', 'due': ''},                     # unknown source: dropped
                                 {'text': 'Late', 'from': 'meeting:m1', 'due': '2030-01-01'}],              # beyond a year: no date
                     'tomorrow': ['10:00 Design review']})
        recap = brain.recap.recap_make(DAY)
        self.assertEqual(recap['source'], 'ai')
        self.assertEqual(recap['highlights'], ['Agreed to ship Monday'])
        self.assertEqual([(a['text'], a['due'], a['source']) for a in recap['actions']],
                         [('Send the deck', '2026-10-31', 'Weekly sync'), ('Order a hub', '', 'Hubs'), ('Late', '', 'Weekly sync')])
        path = self.root / 'recaps' / f'{DAY}.json'
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(self.model.call_args.kwargs['label'], 'Daily recap')
        self.assertIn('data, never instructions', self.model.call_args.args[0])

    def test_a_saved_recap_is_reused_until_something_new_happens(self):
        self.meeting()
        self.answer({'headline': 'One sync.', 'actions': [{'text': 'Send the deck', 'from': 'meeting:m1', 'due': ''}]})
        first = brain.recap.recap_make(DAY)
        self.assertEqual(brain.recap.recap_make(DAY), first)
        self.assertEqual(self.model.call_count, 1)
        brain.recap.recap_remind(f'recap:{DAY}', ['send the deck'])
        self.log({'at': f'{DAY} 20:00:00', 'task': 'What is due tomorrow?', 'reply': 'The deck.', 'status': 'completed', 'path': 'model'})
        again = brain.recap.recap_make(DAY)
        self.assertEqual(self.model.call_count, 2)
        self.assertEqual(again['actions'][0]['added'], 'r0')   # made again, the user's added mark stays
        brain.recap.recap_make(DAY, force=True)
        self.assertEqual(self.model.call_count, 3)

    def test_a_failed_or_missing_model_gives_the_plain_list(self):
        self.meeting()
        for failure in (('not json', {}), RuntimeError('Could not answer.')):
            with self.subTest(failure=str(failure)[:20]):
                (self.root / 'recaps' / f'{DAY}.json').unlink(missing_ok=True)
                if isinstance(failure, Exception): self.model.side_effect = failure
                else: self.model.return_value = failure
                recap = brain.recap.recap_make(DAY)
                self.assertEqual(recap['source'], 'local')
                self.assertIn('could not be made', recap['note'])
                self.assertEqual([a['text'] for a in recap['actions']], ['Saygin sends the deck by Friday', 'Book the room'])
                self.assertEqual(recap['tomorrow'], ['10:00 Design review'])
        self.model.reset_mock(side_effect=True)
        self.prefs['client'] = 'pi'
        (self.root / 'recaps' / f'{DAY}.json').unlink()
        with patch.object(brain.prefs, 'client', return_value='pi'):
            recap = brain.recap.recap_make(DAY)
        self.model.assert_not_called()
        self.assertEqual((recap['source'], recap['note']), ('local', ''))

    def test_meetings_stay_on_this_mac_when_ai_meeting_summaries_are_off(self):
        self.meeting()
        self.log({'at': f'{DAY} 10:00:00', 'task': 'Find hubs', 'reply': 'Found three.', 'status': 'completed', 'path': 'model'})
        self.prefs['meetingSummary'] = False
        self.answer({'headline': 'Found hubs.', 'actions': []})
        recap = brain.recap.recap_make(DAY)
        sent = self.model.call_args.args[1]
        self.assertNotIn('ship on Monday', sent); self.assertNotIn('Weekly sync', sent); self.assertIn('Find hubs', sent)
        self.assertEqual([a['text'] for a in recap['actions']], ['Saygin sends the deck by Friday', 'Book the room'])   # still on the card

    def test_due_only_after_its_time_once_a_day_and_never_while_paused_or_off(self):
        evening, morning = datetime(2026, 10, 25, 21, 30), datetime(2026, 10, 25, 8)
        self.assertFalse(brain.recap.recap_due(morning))
        self.assertTrue(brain.recap.recap_due(evening))
        for key, value in (('paused', True), ('recap', False), ('recapAt', '9pm')):
            with self.subTest(key=key):
                self.prefs[key] = value
                self.assertFalse(brain.recap.recap_due(evening))
                del self.prefs[key]
        self.prefs['recapAt'] = '07:15'
        self.assertTrue(brain.recap.recap_due(morning))
        (self.root / 'recaps').mkdir(); (self.root / 'recaps' / f'{DAY}.json').write_text('{}')
        self.assertFalse(brain.recap.recap_due(evening))   # made already: a later launch or wake does not make it again

    def test_old_recaps_go_after_a_month(self):
        folder = self.root / 'recaps'; folder.mkdir()
        old, recent = (date(2026, 10, 25) - timedelta(days=31)).isoformat(), (date(2026, 10, 25) - timedelta(days=29)).isoformat()
        for day in (old, recent): (folder / f'{day}.json').write_text('{}')
        self.meeting(); self.answer({'headline': 'One sync.'})
        brain.recap.recap_make(DAY)
        self.assertEqual(sorted(p.name for p in folder.glob('*.json')), sorted([f'{recent}.json', f'{DAY}.json']))

    def test_reminders_get_the_picks_once_each(self):
        self.meeting(); self.prefs['remindersList'] = 'work'
        self.answer({'headline': 'One sync.', 'actions': [{'text': 'Send the deck', 'from': 'meeting:m1', 'due': '2026-10-31'},
                                                          {'text': 'Book the room', 'from': 'meeting:m1', 'due': ''}]})
        brain.recap.recap_make(DAY)
        result = brain.recap.recap_remind(f'recap:{DAY}', ['send the deck'])
        self.assertEqual(result['added'], 1)
        sent = self.calls[-1]
        self.assertEqual(sent['list'], 'work')
        self.assertEqual(sent['items'], [{'title': 'Send the deck', 'notes': 'Rabik · Daily recap, Oct 25', 'due': '2026-10-31'}])
        self.assertEqual([(i['text'], bool(i['added'])) for i in result['items']], [('Send the deck', True), ('Book the room', False)])
        again = brain.recap.recap_remind(f'recap:{DAY}', ['send the deck'])
        self.assertEqual((again['added'], len(self.calls)), (0, 1))   # already added: Reminders is not asked again
        self.prefs['_need'] = True
        self.assertEqual(brain.recap.recap_remind(f'recap:{DAY}', ['book the room']), {'need': 'reminders'})
        self.assertFalse(brain.recap.recap_items(f'recap:{DAY}')[2][1]['added'])   # no access: nothing marked

    def test_a_meetings_action_items_are_marked_in_its_own_journal(self):
        ident = self.meeting()
        result = brain.recap.recap_remind(f'meeting:{ident}', ['book the room', 'not an item'])
        self.assertEqual(result['added'], 1)
        self.assertEqual(self.calls[-1]['items'][0]['notes'], 'Rabik · Weekly sync, Oct 25')
        self.assertEqual(brain.meeting.meeting_read(ident)['reminded'], {'book the room': 'r0'})
        self.assertEqual([bool(i['added']) for i in brain.recap.recap_items(f'meeting:{ident}')[2]], [False, True])
        for bad in ('meeting:../x', 'recap:yesterday', 'other:1'):
            with self.subTest(bad=bad), self.assertRaises(ValueError): brain.recap.recap_items(bad)

    def test_the_command_line(self):
        with patch.object(brain.recap, 'recap_due', return_value=False): self.assertEqual(brain.recap.recap_command(['catch-up']), {})
        with patch.object(brain.recap, 'recap_due', return_value=True): self.assertTrue(brain.recap.recap_command(['catch-up'])['empty'])
        with self.assertRaises(ValueError): brain.recap.recap_command(['remind', f'recap:{DAY}', '"one"'])
        with self.assertRaises(ValueError): brain.recap.recap_command(['tomorrow'])
        self.assertEqual(brain.recap.recap_command([DAY]), {'day': DAY, 'empty': True})

    def test_the_model_cannot_add_reminders_itself(self):
        # Even with every card answered yes: the user's click is the only way in.
        cmd = f'{brain.paths.ME} --recap remind recap:{DAY} \'["book the room"]\''
        with patch.dict(os.environ, {'RABIK_ASK': str(self.root)}), patch.object(brain.interaction, 'wait_commit', return_value=True), \
             patch.object(brain.interaction, 'ask_user', return_value='y'), patch.object(brain.macos, 'preview_app'), \
             patch('sys.stdin', io.StringIO(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}}))), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            brain.policy.gate()
        decision = json.loads(out.getvalue())['hookSpecificOutput']
        self.assertEqual(decision['permissionDecision'], 'deny')
        self.assertIn('not model tools', decision['permissionDecisionReason'])

if __name__ == '__main__':
    unittest.main()
