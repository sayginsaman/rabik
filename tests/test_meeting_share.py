"""Sharing a meeting's recap: the text the Share menu gets (never the transcript), where the menu opens, and the hint that lets
Rabik send it through a connector."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.meeting, brain.prompts
from tests import native_source, scratch_dir

ROOT = Path(__file__).resolve().parents[1]


class MeetingShareTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        folder = self.root / 'meetings' / 'm1'; folder.mkdir(parents=True)
        (folder / 'metadata.json').write_text(json.dumps({'title': 'Weekly sync', 'started': 1792929600, 'app': 'Zoom'}))
        events = [{'kind': 'transcript', 'text': 'The secret budget is 18,000.', 'seconds': 5, 'speaker': 'Zoom'},
                  {'kind': 'summary', 'text': 'We agreed to ship on Monday.', 'action_items': ['Sam sends the deck by Friday'], 'revision': [1, None, 5.0]}]
        (folder / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))

    def test_the_shared_text_is_the_recap_never_the_transcript(self):
        m = brain.meeting.meeting_command({'action': 'get', 'id': 'm1'})['meeting']
        self.assertEqual(m['share'].splitlines()[0], 'Weekly sync')
        self.assertIn('· Zoom', m['share'].splitlines()[1])
        self.assertIn('We agreed to ship on Monday.', m['share'])
        self.assertIn('• Sam sends the deck by Friday', m['share'])
        self.assertNotIn('secret budget', m['share'])
        brain.meeting.meeting_append('m1', {'kind': 'summary', 'text': '', 'action_items': [], 'revision': [1, None, 5.0]})
        self.assertIn('No summary yet.', brain.meeting.meeting_command({'action': 'get', 'id': 'm1'})['meeting']['share'])

    def test_the_share_menu_opens_at_the_button_in_settings_and_the_panel(self):
        swift, settings, panel = native_source(), (ROOT / 'ui/settings.html').read_text(), (ROOT / 'ui/meeting.html').read_text()
        self.assertIn('NSSharingServicePicker(items: [text]).show(relativeTo: r, of: web, preferredEdge: .minY)', swift)
        self.assertIn('case "meetingShare": shareText(b["text"] as? String ?? "", in: web, at: b["rect"] as? [Double] ?? [])', swift)
        self.assertIn('case "share": shareText(b["text"] as? String ?? "", in: web, at: b["rect"] as? [Double] ?? [])', swift)
        self.assertIn("post({do:'meetingShare',text:currentMeeting?.share||''", settings)
        self.assertIn("post({do:'share',text:shareRecap", panel)

    def test_rabik_hands_a_send_to_an_agent_with_the_recap(self):
        self.assertIn("(send a recap to Slack/email: hand off)", brain.prompts.SYSTEM)


if __name__ == '__main__':
    unittest.main()
