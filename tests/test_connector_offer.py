"""Connector offers: opening Notion, Slack, Linear, Figma, Asana or ClickUp while its Claude connector isn't connected shows one
card in the box; Connect, Not now (a week) or Don't ask again; never during a call, an ask or dictation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
from tests import native_source, run_swift

ROOT = Path(__file__).resolve().parents[1]
OFFER = (ROOT / 'Sources/Rabik/App/ConnectorOffer.swift').read_text()


class ConnectorOfferTests(unittest.TestCase):
    def test_who_gets_an_offer(self):
        apps = OFFER[OFFER.index('    static let apps'):OFFER.index('    private var connected')]
        wanted = OFFER[OFFER.index('    static func wanted'):OFFER.index('    private var quiet: Bool')]
        swift = 'import Cocoa\nfinal class ConnectorOffer {\n' + apps + wanted + '}\n' + r'''
enum Prefs { static var d: [String: Any] = ["connectorOffers": true, "client": "claude"]
    static func bool(_ k: String) -> Bool { d[k] as? Bool ?? false }; static func str(_ k: String) -> String { d[k] as? String ?? "" } }
precondition(ConnectorOffer.wanted("notion.id") && ConnectorOffer.wanted("com.tinyspeck.slackmacgap"))
precondition(!ConnectorOffer.wanted("com.apple.Safari"), "an app with no connector")
Prefs.d["connectorMuted"] = ["notion.id"]; precondition(!ConnectorOffer.wanted("notion.id"), "Don't ask again")
Prefs.d["connectorSnooze"] = ["com.linear": Date().addingTimeInterval(3600).timeIntervalSince1970]
precondition(!ConnectorOffer.wanted("com.linear") && ConnectorOffer.wanted("com.linear", now: Date().addingTimeInterval(7200)), "Not now waits")
Prefs.d["client"] = "devin"; precondition(!ConnectorOffer.wanted("com.figma.Desktop"), "connectors are Claude's")
Prefs.d["client"] = "claude"; Prefs.d["connectorOffers"] = false; precondition(!ConnectorOffer.wanted("com.figma.Desktop"), "the switch")
print("offers ok")
'''
        self.assertIn('offers ok', run_swift(self, swift))

    def test_quiet_moments_and_once_a_launch(self):
        self.assertIn('meeting.panel != nil || app.busy || app.engine.isRunning || app.dictating || app.panel.isVisible || !callAppsOnMic().isEmpty', OFFER)
        self.assertIn('guard !offered.contains(bundle), ConnectorOffer.wanted(bundle), !quiet', OFFER)
        self.assertIn('if Date().timeIntervalSince(checked) < 6 * 3600 { return show() }', OFFER)
        self.assertIn('case "connect": checked = .distantPast; onboarding.grant("connectors")', OFFER)
        source = native_source()
        self.assertIn('"connectorOffers": true', source[source.index('static let defaults'):source.index('static let retiredKeys')])
        self.assertIn('<input type="checkbox" data-k="connectorOffers">', (ROOT / 'ui/settings.html').read_text())


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class ConnectorCardPageTests(unittest.TestCase):
    def test_the_card_says_what_it_reads_and_answers(self):
        from tests.test_shelf_page import HARNESS
        harness = HARNESS.replace('cfg.userContentController.add(h, name: "agents")', 'cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")')
        harness = harness.replace('?["action"] as? String == "ready"', '?["ready"] != nil')
        script = r'''
            ui.connectorOffer({app: 'notion.id', name: 'Notion', reads: 'search and read your pages and databases'});
            const d = document.querySelector('.connector-card'), text = [d.querySelector('b').textContent, d.querySelector('.a').textContent, [...d.querySelectorAll('.agent-actions button')].map(b => b.textContent)];
            ui.agentEscape(); const gone = !document.querySelector('.connector-card');
            ui.connectorOffer({app: 'com.linear', name: 'Linear', reads: 'read your issues and projects'}); document.querySelector('.connector-card .go').click();
            return [text, gone];'''
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'ui.html', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(harness)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), script], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(got['result'], [['Let Rabik and your agents use Notion?', 'Connect Notion in Claude so Rabik can search and read your pages and databases when you ask.',
                                          ['Don’t ask again', 'Not nowesc', 'Connect↩']], True])
        self.assertIn({'connectorOffer': {'choice': 'later', 'app': 'notion.id'}}, got['posts'])
        self.assertIn({'connectorOffer': {'choice': 'connect', 'app': 'com.linear'}}, got['posts'])


if __name__ == '__main__':
    unittest.main()
