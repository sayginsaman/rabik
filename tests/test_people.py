"""People: built from saved meetings (calendar attendees, speaker names) and About you's People facts; one person however
they were spelled; --people answers "when did I last talk to Sam" with a person chip; Settings lists them and can hide one."""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.cli, brain.memory, brain.people, brain.prefs
from tests import native_source, scratch_dir

ROOT = Path(__file__).resolve().parents[1]


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        own = patch.object(brain.memory, 'ME_FILE', str(self.root / 'me.json')); own.start(); self.addCleanup(own.stop)   # About you, this test's own
        def meeting(ident, title, started, people=(), speakers=()):
            folder = self.root / 'meetings' / ident; folder.mkdir(parents=True)
            (folder / 'metadata.json').write_text(json.dumps({'title': title, 'started': started, 'app': 'Zoom', 'people': list(people)}))
            rows = [{'kind': 'transcript', 'text': 'Hi.', 'seconds': i, 'speaker': s} for i, s in enumerate(speakers)] + [{'kind': 'transcript', 'text': 'Me.', 'seconds': 9, 'speaker': 'You', 'mic': True}]
            (folder / 'events.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        meeting('m1', 'Pricing review', 1792929600, people=[{'name': 'Sam Lee', 'email': 'Sam@Acme.com'}, {'name': '', 'email': 'priya@acme.com'}], speakers=['Zoom'])
        meeting('m2', 'Hiring sync', 1793016000, speakers=['Sam', 'Priya Shah', 'Them'])
        brain.memory.profile_add('people', 'works at Acme as head of sales', kind='Sam Lee')
        brain.memory.profile_add('people', 'my sister, lives in Izmir', kind='Deniz')

    def test_one_person_however_spelled_with_meetings_and_facts(self):
        people = {p['name']: p for p in brain.people.people_all()}
        self.assertEqual(sorted(people), ['Deniz', 'Priya Shah', 'Sam Lee'])
        sam = people['Sam Lee']
        self.assertEqual((sam['email'], sam['id']), ('sam@acme.com', 'sam@acme.com'))
        self.assertEqual([m['id'] for m in sam['meetings']], ['m2', 'm1'])   # "Sam" speaking in m2 is Sam Lee
        self.assertEqual(sam['last'], 1793016000)
        self.assertEqual(sam['facts'], ['Sam Lee: works at Acme as head of sales'])
        self.assertEqual(people['Deniz']['facts'], ['my sister, lives in Izmir'])
        self.assertNotIn('Zoom', people)   # an app name is no person

    def test_a_question_about_someone_and_its_chip(self):
        ask = self.root / 'ask'; ask.mkdir()
        with patch.dict(os.environ, {'RABIK_ASK': str(ask)}): text = brain.people.people_find('when did I last talk to Sam')
        self.assertTrue(text.startswith('Sam Lee <sam@acme.com>\nLast met: '))
        self.assertIn('- Meeting: Hiring sync', text)
        self.assertEqual(json.loads((ask / 'sources.jsonl').read_text().splitlines()[0])['kind'], 'person')
        self.assertEqual(brain.people.people_find('Zed'), 'Nobody by that name in meetings or About you.')

    def test_hidden_people_stay_out_and_settings_get_json(self):
        with patch.object(brain.prefs, 'pref', side_effect=lambda k, d=None: ['sam@acme.com'] if k == 'peopleHidden' else d):
            self.assertNotIn('Sam Lee', [p['name'] for p in brain.people.people_all()])
        with patch.object(sys, 'argv', ['rabik.py', '--people', 'list']), patch('sys.stdout', new_callable=io.StringIO) as out:
            brain.cli.main()
        self.assertIn('Sam Lee', [p['name'] for p in json.loads(out.getvalue())['people']])

    def test_meetings_keep_their_attendees_and_settings_has_people(self):
        meeting, swift, page = (ROOT / 'Sources/Rabik/Meeting/Meeting.swift').read_text(), native_source(), (ROOT / 'ui/settings.html').read_text()
        self.assertIn('if !people.isEmpty { metadata["people"] = people }', meeting)
        self.assertIn('app: callApp, started: began, people: attendees)', meeting)
        self.assertIn('let p = py(["--people", "list"])', swift)
        self.assertIn('<section id="people">', page)
        self.assertIn("set('peopleHidden',[...(P.peopleHidden||[]),currentPerson.id])", page)
        self.assertIn('case "person": Rabik.settings.open(tab: "people", then: "showPerson", id)', swift)


if __name__ == '__main__':
    unittest.main()
