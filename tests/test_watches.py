"""Watches that press a button: "if ChatGPT asks for permission, allow it" registers a watch the user confirmed on a card, Rabik.app
presses that button in that app whenever it shows (never one that loses data or money, never in Rabik), until it is stopped."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.cli, brain.paths, brain.prompts, brain.watcher
from tests import scratch_dir

ROOT = Path(__file__).resolve().parents[1]
AUTO = (ROOT / 'Sources/Rabik/App/AutoPress.swift').read_text()


def cli(*args):
    with patch.object(sys, 'argv', ['rabik.py', *args]), patch('sys.stdout', new_callable=io.StringIO) as out:
        brain.cli.main()
    return out.getvalue().strip()


class PressWatchTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        watching = patch.object(brain.watcher, 'WATCHING', str(self.root / 'watching')); watching.start(); self.addCleanup(watching.stop)

    def test_a_press_watch_is_saved_listed_and_stopped(self):
        said = cli('--watch', 'press', 'ChatGPT', 'Allow|Approve')
        self.assertEqual(said, 'Watching ChatGPT: Rabik clicks “Allow” or “Approve” whenever it shows, until you say stop watching.')
        rows = json.loads((self.root / 'watches.json').read_text())
        self.assertEqual((rows[0]['app'], rows[0]['labels'], rows[0]['kind']), ('ChatGPT', ['Allow', 'Approve'], 'press'))
        self.assertEqual(oct((self.root / 'watches.json').stat().st_mode & 0o777), '0o600')
        self.assertEqual(cli('--watch', 'press', 'chatgpt', 'allow|approve'), 'Already watching chatgpt for allow or approve.')
        self.assertIn('clicks “Allow” or “Approve” in ChatGPT until stopped', cli('--watches'))
        cli('--watch', 'press', 'Codex', 'Run')
        first = rows[0]['id']
        self.assertEqual(cli('--unwatch', first), 'Stopped that watch.')
        self.assertEqual([r['app'] for r in brain.watcher.press_watches()], ['Codex'])
        self.assertEqual(cli('--unwatch'), 'stopped 1 watch(es)')
        self.assertEqual(cli('--watches'), 'No watches.')
        self.assertEqual(cli('--unwatch', 'abcdef12'), 'That watch is not running.')

    def test_it_never_presses_what_loses_data_or_money_nor_in_rabik(self):
        for label in ('Delete', 'Empty Trash', 'Buy now', 'Allow|Erase'):
            self.assertIn('never presses a button like that', cli('--watch', 'press', 'Finder', label))
        self.assertIn("doesn't press its own buttons", cli('--watch', 'press', 'Rabik', 'Allow'))
        self.assertEqual(brain.watcher.press_watches(), [])

    def test_the_ai_gets_the_usage_and_the_user_a_card(self):
        self.assertEqual(cli('--watch', '--help'), brain.prompts.WATCH_HELP)
        self.assertIn('press "ChatGPT" "Allow|Approve"', brain.prompts.WATCH_HELP)
        self.assertIn('never "Always allow" unless they asked for it', brain.prompts.WATCH_HELP)

    def test_the_app_presses_only_named_buttons_outside_rabik_and_never_while_paused(self):
        self.assertIn('$0.bundleIdentifier != me && $0.activationPolicy == .regular', AUTO)
        self.assertIn('guard !rows.isEmpty, !busy, !Prefs.bool("paused"), AXIsProcessTrusted() else { return }', AUTO)
        self.assertIn('while next < queue.count, next < 3000 {', AUTO)
        self.assertIn('guard Date().timeIntervalSince(noticed[id] ?? .distantPast) >= 60 else { return }', AUTO)   # one notice a minute
        self.assertIn('autoPress.start()', (ROOT / 'Sources/Rabik/main.swift').read_text())


@unittest.skipUnless(sys.platform == 'darwin', 'macOS AppKit check')
class PressNativeTests(unittest.TestCase):
    def test_a_real_window_gets_its_named_button_pressed_and_no_other(self):
        helpers = 'import Cocoa\nenum AutoPress {\n' + AUTO[AUTO.index('    static func press'):]
        harness = r'''import Cocoa
final class Target: NSObject { var hits: [String] = []; @objc func hit(_ s: NSButton) { hits.append(s.title) } }
let app = NSApplication.shared; app.setActivationPolicy(.accessory)
let t = Target(), w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 300, height: 120), styleMask: [.titled], backing: .buffered, defer: false)
for (i, title) in ["Delete", "Allow"].enumerated() { let b = NSButton(title: title, target: t, action: #selector(Target.hit(_:))); b.frame = NSRect(x: 10 + 140 * i, y: 10, width: 120, height: 30); w.contentView?.addSubview(b) }
w.orderFrontRegardless()
DispatchQueue.global().asyncAfter(deadline: .now() + 0.5) {
    let a = AutoPress.press(getpid(), labels: ["Approve", "allow"]), b = AutoPress.press(getpid(), labels: ["Run"])
    DispatchQueue.main.async { print(a ?? "-", b ?? "-", t.hits.joined(separator: ",")); exit(0) }
}
DispatchQueue.main.asyncAfter(deadline: .now() + 10) { print("timeout"); exit(1) }
app.run()
'''
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'a.swift').write_text(helpers); (Path(tmp) / 'main.swift').write_text(harness)
            built = subprocess.run(['swiftc', str(Path(tmp) / 'main.swift'), str(Path(tmp) / 'a.swift'), '-o', str(Path(tmp) / 'press')], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(Path(tmp) / 'press')], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.stdout.strip(), 'allow - Allow')


if __name__ == '__main__':
    unittest.main()
