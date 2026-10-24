"""Run mock-bridge HTML fixtures in a temporary WebKit host, never the installed app."""
import functools
import http.server
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit fixtures')
class FixtureTests(unittest.TestCase):
    def test_main_overlay_fixture(self):
        self.check_fixtures(['ui'])

    def test_timer_row_fixture(self):
        self.check_fixtures(['timer_row'])

    def test_box_contrast_fixture(self):
        self.check_fixtures(['contrast'])

    def test_mock_bridge_fixtures(self):
        self.check_fixtures(['settings', 'worksheet', 'meeting', 'onboarding', 'web', 'agents', 'agent_done'])

    def test_fixtures_inline_orbs_literally(self):
        # A string replacement expands $' and $& inside orbs.js (its TeX table has '$'), so the page gets a broken module.
        for page in ROOT.glob('tests/*.html'):
            self.assertIsNone(re.search(r"replace\('/\*ORBS\*/',\s*[^\s(]", page.read_text()), page.name)

    def check_fixtures(self, names):
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(ROOT)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        swift = '''import Cocoa
import WebKit
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let activity = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .idleDisplaySleepDisabled], reason: "Atticus isolated WebKit fixtures")
let config = WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent()   // a disk cache keyed by the reused port served the last run's ui/*.js
let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1000, height: 900), configuration: config)
let panel = NSPanel(contentRect: web.frame, styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
panel.contentView = web; panel.sharingType = .none
panel.ignoresMouseEvents = true   // nonactivating fixture windows exercise real compositor frames without changing the user's focus
panel.orderFrontRegardless()
web.load(URLRequest(url: URL(string: CommandLine.arguments[1])!))
var tries = 0
var lastCheck = ""
Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { timer in
 tries += 1
 web.evaluateJavaScript("(()=>{const r=document.getElementById('results');return {status:r?.className,text:r?.className?r.textContent:r?.dataset.lastCheck||r?.textContent};})()") { result, error in
  if let result = result as? [String:String], let text = result["text"], text != lastCheck {
   lastCheck = text; print(text.split(separator:"\\n").last ?? ""); fflush(stdout)
  }
  if let result = result as? [String: String], ["pass", "fail"].contains(result["status"] ?? "") {
   print(result["text"] ?? ""); exit(result["status"] == "pass" ? 0 : 1)
  }
  if tries > 200 { print("Fixture timed out"); exit(2) }
 }
}
app.run()
'''
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'fixture.swift'; source.write_text(swift)
            binary = Path(root) / 'fixture'
            compiled = subprocess.run(['swiftc', str(source), '-o', str(binary)], text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            for name in names:
                with self.subTest(fixture=name):
                    try:
                        result = subprocess.run([str(binary), f'http://127.0.0.1:{server.server_port}/tests/{name}.html'], capture_output=True, text=True, timeout=25)
                    except subprocess.TimeoutExpired as error:
                        self.fail(f'{name} timed out; last checks: {(error.stdout or b"").decode()[-3000:]}')
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    if 'MEASURED:' in result.stdout: print(result.stdout.rsplit('MEASURED:', 1)[1].strip(), flush=True)
