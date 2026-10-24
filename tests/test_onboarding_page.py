"""Onboarding layout checks in an offscreen WKWebView: no app, window, or user settings."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''import Cocoa
import WebKit
final class Harness: NSObject, WKNavigationDelegate {
    func webView(_ view: WKWebView, didFinish navigation: WKNavigation!) {
        view.evaluateJavaScript("""
        (()=>{
          const filler = ' Extra setup guidance that can wrap onto several lines on a small display.'.repeat(5);
          for (const id of ['list', 'own', 'yours']) {
            const list = document.getElementById(id);
            if (!list.children.length) list.innerHTML = Array.from({length: id === 'list' ? 7 : 4}, (_, i) =>
              `<div class="row"><div class="txt"><b>Permission ${i + 1}</b><span>Why this permission is needed.${filler}</span></div><button class="allow">Allow</button></div>`).join('');
          }
          document.querySelectorAll('p.sub, .txt span, .done-note').forEach(node => node.textContent += filler);
          const rows = [];
          for (const page of document.querySelectorAll('.page')) {
            document.querySelectorAll('.page').forEach(other => other.classList.toggle('on', other === page));
            page.inert = false;
            page.scrollTop = 0;
            page.scrollTop = page.scrollHeight;
            void page.offsetHeight;
            const frame = page.getBoundingClientRect();
            const actions = [...page.querySelectorAll(':scope > .bar2 button, :scope > button.btn')]
              .filter(button => !button.hidden && getComputedStyle(button).display !== 'none');
            rows.push({
              id: page.id,
              horizontal: page.scrollWidth <= page.clientWidth + 1,
              actions: actions.length,
              reachable: actions.every(button => {
                const rect = button.getBoundingClientRect();
                return rect.top >= frame.top - 1 && rect.bottom <= frame.bottom + 1;
              })
            });
          }
          const sheet = document.getElementById('prov');
          sheet.hidden = false;
          sheet.querySelector('p').textContent += filler;
          sheet.scrollTop = sheet.scrollHeight;
          void sheet.offsetHeight;
          const card = sheet.querySelector('.card').getBoundingClientRect(), frame = sheet.getBoundingClientRect();
          return JSON.stringify({rows, sheet: {
            horizontal: sheet.scrollWidth <= sheet.clientWidth + 1,
            reachable: card.left >= frame.left - 1 && card.right <= frame.right + 1 &&
              sheet.querySelector('.acts').getBoundingClientRect().bottom <= frame.bottom + 1
          }});
        })()
        """) { value, error in
            if let error { print(error); exit(1) }
            if let value {
                if let text = value as? NSString {
                    print(text); exit(0)
                } else {
                    print("no result"); exit(2)
                }
            } else { print("no result"); exit(2) }
        }
    }
}
let app = NSApplication.shared
let harness = Harness(), width = Double(CommandLine.arguments[2])!, height = Double(CommandLine.arguments[3])!
let view = WKWebView(frame: NSRect(x: 0, y: 0, width: width, height: height))
view.navigationDelegate = harness
view.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 20) { print("timeout"); exit(3) }
app.run()
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class OnboardingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        html = (ROOT / 'ui/onboarding.html').read_text()
        bridge = """<script>window.webkit={messageHandlers:new Proxy({}, {get:()=>({postMessage(){}})})};</script>"""
        cls.page = Path(cls.tmp.name) / 'onboarding.html'
        cls.page.write_text(re.sub(r'<script\b.*?</script>', '', html, flags=re.S).replace('<head>', '<head>' + bridge, 1))
        source, cls.binary = Path(cls.tmp.name) / 'page.swift', Path(cls.tmp.name) / 'page'
        source.write_text(HARNESS)
        built = subprocess.run(['swiftc', str(source), '-o', str(cls.binary)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_page_and_provider_sheet_scroll_at_small_sizes(self):
        for width, height in ((640, 612), (480, 420), (360, 320)):
            with self.subTest(size=(width, height)):
                result = subprocess.run(
                    [str(self.binary), str(self.page), str(width), str(height)],
                    capture_output=True, text=True, timeout=30, env={**os.environ, 'ATTICUS_DIR': self.tmp.name})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                measured = json.loads(result.stdout.strip().splitlines()[-1])
                self.assertTrue(measured['sheet']['horizontal'])
                self.assertTrue(measured['sheet']['reachable'])
                for page in measured['rows']:
                    self.assertTrue(page['horizontal'], f"{page['id']} overflows horizontally at {width}×{height}")
                    self.assertGreater(page['actions'], 0, f"{page['id']} has no action")
                    self.assertTrue(page['reachable'], f"{page['id']} action is unreachable at {width}×{height}")


if __name__ == '__main__':
    unittest.main()
