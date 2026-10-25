"""Goals: said ("my goal is…", "hedefim…") or added in Settings, at most five open; done by a word from them; the daily recap's
one AI call may say which goals the day moved forward, and only goals the user has."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.goals, brain.instant, brain.recap
from tests import scratch_dir


class GoalsTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)

    def say(self, text):
        return brain.instant.fast(text).reply

    def test_said_added_listed_and_done(self):
        self.assertEqual(self.say('My goal is to ship the beta by Friday.'), 'Goal added: ship the beta by Friday. The daily recap will say when your day moves it forward.')
        self.assertEqual(self.say('Hedefim: haftada 3 kez spor'), 'Goal added: haftada 3 kez spor. The daily recap will say when your day moves it forward.')
        self.assertEqual(self.say('my goal is to ship the beta by friday'), '“ship the beta by friday” is already a goal.')
        self.assertEqual(self.say('what are my goals'), 'Your goals: ship the beta by Friday; haftada 3 kez spor.')
        self.assertEqual(self.say('I finished the beta goal'), 'Done: ship the beta by Friday. Nice work.')
        self.assertEqual(self.say('spor hedefini tamamladım'), 'Done: haftada 3 kez spor. Nice work.')
        self.assertEqual(self.say('what are my goals'), 'No goals yet. Say “my goal is …”.')
        self.assertIsNone(self.say('my goal is to learn Swift, how do I start?'))   # a question is for the AI
        self.assertEqual(oct((self.root / 'goals.json').stat().st_mode & 0o777), '0o600')

    def test_five_open_at_most_and_settings_commands(self):
        for i in range(5): brain.goals.goal_add(f'goal number {i}')
        self.assertIn('You have 5 goals', brain.goals.goal_add('one more'))
        first = brain.goals.goals()[0]['id']
        self.assertEqual(brain.goals.goals_command(['done', first])['goals'][0]['done'] > 0, True)
        self.assertEqual(brain.goals.goals_command(['undo', first])['goals'][0]['done'], 0)
        self.assertEqual(len(brain.goals.goals_command(['drop', first])['goals']), 4)
        with self.assertRaises(ValueError): brain.goals.goals_command(['drop', '../x'])

    def test_the_recap_keeps_only_the_users_goals(self):
        inputs = {'day': '2026-10-25', 'asks': [], 'instant': 0, 'agents': [], 'meetings': [], 'tomorrow': [], 'goals': ['Ship the beta']}
        text = json.dumps({'headline': 'A good day', 'goals': [{'goal': 'ship the beta', 'note': 'Two agents finished the tests.'},
                                                              {'goal': 'Become famous', 'note': 'Invented.'}, {'goal': 'Ship the beta', 'note': ''}]})
        self.assertEqual(brain.recap.recap_check(text, inputs)['goals'], [{'goal': 'Ship the beta', 'note': 'Two agents finished the tests.'}])
        self.assertIn('"goals"', brain.recap.RECAP_SYSTEM)
        brain.goals.goal_add('Ship the beta')
        with patch.object(brain.recap.agents, 'agent_history', return_value=[]), patch.object(brain.recap.meeting, 'meeting_list', return_value=[]), \
             patch.object(brain.recap, 'recap_tomorrow', return_value=[]):
            self.assertEqual(brain.recap.recap_inputs('2026-10-25')['goals'], ['Ship the beta'])


if __name__ == '__main__':
    unittest.main()
