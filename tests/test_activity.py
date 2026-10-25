"""Activity history: off until turned on; Rabik.app notes the window in front (title, file, page) one file a day, never private
windows or password managers; --activity finds what the user had open, its pages become source chips, and the daily recap
lists where the day went."""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.activity, brain.prefs, brain.recap
from tests import native_source, run_swift, scratch_dir

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = (ROOT / 'Sources/Rabik/App/Activity.swift').read_text()


def at(day, hour, minute=0):
    return datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute).timestamp()


class ActivitySearchTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        folder = self.root / 'activity'; folder.mkdir()
        today, yesterday, old = date.today(), date.today() - timedelta(days=1), date.today() - timedelta(days=40)
        rows = {yesterday: [{'start': at(yesterday, 10), 'end': at(yesterday, 10, 25), 'app': 'Figma', 'bundle': 'com.figma.Desktop', 'title': 'Pricing page v3', 'path': '/Users/u/Pricing.fig'},
                            {'start': at(yesterday, 11), 'end': at(yesterday, 11, 5), 'app': 'Safari', 'bundle': 'com.apple.Safari', 'title': 'Stripe pricing', 'url': 'https://stripe.com/pricing'}],
                today: [{'start': at(today, 9), 'end': at(today, 9, 40), 'app': 'Xcode', 'bundle': 'com.apple.dt.Xcode', 'title': 'App.swift'},
                        {'start': at(today, 10), 'end': at(today, 10, 3), 'app': 'Safari', 'bundle': 'com.apple.Safari', 'title': 'Stripe pricing', 'url': 'https://stripe.com/pricing'}],
                old: [{'start': at(old, 9), 'end': at(old, 10), 'app': 'Notes', 'bundle': 'com.apple.Notes', 'title': 'Pricing ideas'}]}
        for day, items in rows.items():
            (folder / f'{day.isoformat()}.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in items) + 'not json\n')
        self.on = patch.object(brain.prefs, 'pref', side_effect=lambda k, d=None: True if k == 'activity' else d)
        self.on.start(); self.addCleanup(self.on.stop)

    def test_finds_by_words_and_day_and_adds_up_the_time(self):
        found = brain.activity.activity_search('the figma file I looked at yesterday').splitlines()
        self.assertEqual(len(found), 1)
        self.assertIn('Figma · Pricing page v3 · /Users/u/Pricing.fig (25 min)', found[0])
        pricing = brain.activity.activity_search('pricing').splitlines()
        self.assertIn('Stripe pricing · https://stripe.com/pricing (8 min)', pricing[1])   # both days, put together
        self.assertNotIn('Pricing ideas', '\n'.join(pricing))   # older than 30 days

    def test_its_pages_and_files_become_source_chips(self):
        ask = self.root / 'ask'; ask.mkdir()
        with patch.dict(os.environ, {'RABIK_ASK': str(ask)}): brain.activity.activity_search('pricing')
        rows = [json.loads(line) for line in (ask / 'sources.jsonl').read_text().splitlines()]
        self.assertEqual([(r['kind'], r['id']) for r in rows], [('activity', '/Users/u/Pricing.fig'), ('activity', 'https://stripe.com/pricing')])

    def test_off_says_where_to_turn_it_on_and_the_recap_lists_where_the_day_went(self):
        self.assertEqual(brain.activity.activity_day(date.today().isoformat()), ['App.swift · Xcode · 40 min', 'Stripe pricing · Safari · 3 min'])
        self.on.stop()
        with patch.object(brain.prefs, 'pref', side_effect=lambda k, d=None: False if k == 'activity' else d):
            self.assertIn('Settings → Memory', brain.activity.activity_search('pricing'))
            self.assertEqual(brain.activity.activity_day(date.today().isoformat()), [])
        self.on.start()

    def test_the_recap_keeps_its_ai_part_and_refreshes_where_the_day_went(self):
        inputs = {'day': date.today().isoformat(), 'asks': [{'at': '09:00', 'asked': 'x', 'answer': 'y'}], 'instant': 0, 'agents': [], 'meetings': [], 'tomorrow': [], 'private': False}
        with patch.object(brain.recap, 'recap_inputs', return_value=inputs), patch.object(brain.recap.prefs, 'client', return_value='devin'):
            first = brain.recap.recap_make()
            self.assertEqual(first['focus'], ['App.swift · Xcode · 40 min', 'Stripe pricing · Safari · 3 min'])
            with patch.object(brain.activity, 'activity_day', return_value=['App.swift · Xcode · 55 min']):
                self.assertEqual(brain.recap.recap_make()['focus'], ['App.swift · Xcode · 55 min'])


class ActivityNativeTests(unittest.TestCase):
    def test_off_until_turned_on_and_private_windows_are_never_noted(self):
        source = native_source()
        defaults = source[source.index('static let defaults'):source.index('static let retiredKeys')]
        self.assertIn('"activity": false', defaults)
        self.assertIn('activity.sync()', (ROOT / 'Sources/Rabik/main.swift').read_text())
        for bundle in ('org.torproject.torbrowser', 'com.1password.1password', 'com.bitwarden.desktop', 'com.apple.Passwords'):
            self.assertIn(bundle, ACTIVITY)
        self.assertIn('guard !locked, idle < 300, !skipped.contains(bundle)', ACTIVITY)
        self.assertIn('guard (row["end"] as? Double ?? 0) - (row["start"] as? Double ?? 0) >= 10 else { return }', ACTIVITY)
        self.assertIn('attributes: [.posixPermissions: 0o600]', ACTIVITY)
        swift = 'import Cocoa\n' + ACTIVITY.split('import Cocoa', 1)[1].replace('final class Activity {', 'final class Activity {\n', 1) + r'''
enum Prefs { static var path = "/tmp/x/settings.json"; static var d: [String: Any] = [:]; static func bool(_ k: String) -> Bool { false } }
precondition(Activity.isPrivate("Inbox — Mozilla Firefox Private Browsing") && Activity.isPrivate("Docs - Google Chrome (Incognito)") && Activity.isPrivate("[InPrivate] Bing"))
precondition(!Activity.isPrivate("Private repos · GitHub") && !Activity.isPrivate("Pricing page v3"))
precondition(Activity.same(["bundle": "a", "title": "t", "url": "u"], ["bundle": "a", "title": "t", "url": "u"]))
precondition(!Activity.same(["bundle": "a", "title": "t", "url": "u"], ["bundle": "a", "title": "t", "url": "v"]))
print("activity ok")
'''
        self.assertIn('activity ok', run_swift(self, swift))

    def test_settings_add_clear_and_exclude(self):
        page, settings = (ROOT / 'ui/settings.html').read_text(), (ROOT / 'Sources/Rabik/Settings/SettingsWindow.swift').read_text()
        self.assertIn('<input type="checkbox" data-k="activity">', page)
        self.assertIn('guard confirm("Clear activity history?"', settings)
        self.assertIn('if k == "activity" { activity.sync() }', settings)
        self.assertIn("list('Most time on',r.focus||[])", (ROOT / 'ui/ui.html').read_text())


if __name__ == '__main__':
    unittest.main()
