"""Feedback worker failure uses a scratch executable path and no app windows."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'macOS native feedback worker')
class FeedbackNativeTests(unittest.TestCase):
    def test_failed_worker_clears_url_and_reports_latest_error_without_crashing(self):
        source = (ROOT / 'Atticus.swift').read_text()
        method = source[source.index('    func feedbackPreview('):source.index('    // "Change shortcut":')]
        swift = '''import Cocoa
func py(_ args:[String])->Process { let p=Process();p.executableURL=URL(fileURLWithPath:CommandLine.arguments[1]+"/missing-worker");return p }
enum Updater { static let version="fixture" }
final class Harness {
 var feedbackJob=0,feedbackURL:URL?,web:Bool?=true
 func send(_ name:String,_ value:Any) {
  precondition(name=="feedback" && (value as? [String:Any])?["error"] != nil)
  precondition(feedbackURL == nil && feedbackJob == 2)
  print("feedback failed worker: private URL cleared; latest error shown");exit(0)
 }
''' + method + '''}
let h=Harness();h.feedbackURL=URL(string:"https://fixture.invalid/private-draft")
h.feedbackPreview(true,"");h.feedbackPreview(false,"")
precondition(h.feedbackURL == nil)
RunLoop.current.run(until:Date().addingTimeInterval(3));exit(1)
'''
        with tempfile.TemporaryDirectory(prefix='atticus-feedback-fixture-') as tmp:
            root=Path(tmp);file=root/'feedback.swift';file.write_text(swift);binary=root/'feedback'
            result=subprocess.run(['swiftc',str(file),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(binary),tmp],env={**os.environ,'ATTICUS_DIR':tmp},capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
