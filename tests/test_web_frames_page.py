"""ui/web.js's read in a real WKWebView that is never put in a window: a form in another site's frame is named, not silently dropped."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''import Cocoa
import WebKit
// Serves argv[1] (JSON {"host/path": html}) on fixture://, loads fixture://site.test/apply.html, then runs web.js (argv[2]) read.
final class Pages: NSObject, WKURLSchemeHandler, WKNavigationDelegate {
    let pages = try! JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: String]
    func webView(_ w: WKWebView, start task: WKURLSchemeTask) {
        let url = task.request.url!, body = Data((pages[(url.host ?? "") + url.path] ?? "").utf8)
        task.didReceive(URLResponse(url: url, mimeType: "text/html", expectedContentLength: body.count, textEncodingName: "utf-8"))
        task.didReceive(body); task.didFinish()
    }
    func webView(_ w: WKWebView, stop task: WKURLSchemeTask) {}
    func webView(_ w: WKWebView, didFinish _: WKNavigation!) {
        let src = try! String(contentsOfFile: CommandLine.arguments[2], encoding: .utf8)
        w.callAsyncJavaScript("return (0, eval)(src)('read', '', '')", arguments: ["src": src], in: nil, in: .page) { r in
            switch r {
            case .success(let x): print(x as? String ?? "not text"); exit(0)
            case .failure(let e): print(e); exit(1)
            }
        }
    }
}
NSApplication.shared.setActivationPolicy(.prohibited)   // no Dock icon, no menu, no window
let pages = Pages(), cfg = WKWebViewConfiguration()
cfg.setURLSchemeHandler(pages, forURLScheme: "fixture")
let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 800, height: 400), configuration: cfg)
web.navigationDelegate = pages
web.load(URLRequest(url: URL(string: "fixture://site.test/apply.html")!))
DispatchQueue.main.asyncAfter(deadline: .now() + 30) { print("timeout"); exit(1) }
NSApplication.shared.run()
'''
PAGES = {
    'site.test/apply.html': '<title>Careers</title><h1>Account executive</h1><input placeholder="Enter work email"><button>Continue</button>'
                            '<iframe src="fixture://site.test/inner.html" style="height:60px"></iframe>'
                            '<iframe src="fixture://ads.test/pixel.html" width="1" height="1"></iframe>'
                            '<div style="height:1200px"></div><iframe src="fixture://forms.test/form.html" style="width:600px;height:300px"></iframe>',
    'site.test/inner.html': '<input aria-label="Promo code">',
    'forms.test/form.html': '<label>First Name <input></label><label>Last Name <input></label>',
    'ads.test/pixel.html': '<p>tracker</p>',
}


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class WebFramesPageTests(unittest.TestCase):
    def test_another_sites_form_frame_is_named_with_where_it_is_and_how_to_reach_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            pages, src, binary = Path(tmp) / 'pages.json', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            pages.write_text(json.dumps(PAGES)); src.write_text(HARNESS)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(pages), str(ROOT / 'ui/web.js')], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        read = run.stdout
        controls = read.split('\n\nPage text:')[0]
        self.assertIn('Frame from forms.test (below the view): its fields and text are NOT in this read. Scroll to it, then --hands see/type.', controls)
        self.assertTrue(controls.startswith('Controls:\nFrame from forms.test'), read)   # first: a long page's text never pushes it past the first 8000 chars
        self.assertNotIn('First Name', read)   # the page script truly cannot see it; the note is the only trace
        self.assertNotIn('ads.test', read)   # a tracking pixel is not a form
        self.assertRegex(controls, r'\d+ box: Enter work email')
        self.assertRegex(controls, r'\d+ box: Promo code')   # a same-site frame is still read in full


if __name__ == '__main__':
    unittest.main()
