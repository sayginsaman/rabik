"""VM-only Swift preference migration, with scratch state and no windows."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'Swift preferences')
class RoutingPreferencesTests(unittest.TestCase):
    def test_native_migration_matches_brain_and_persists_on_next_write(self):
        source = (ROOT / 'Atticus.swift').read_text()
        prefs = source[source.index('enum Prefs {'):source.index('\nfunc applySharing')]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file, binary = root / 'prefs.swift', root / 'prefs'
            file.write_text('import Foundation\nlet controlKey = 1, optionKey = 2\n' + prefs +
                            '\nprecondition(Prefs.bool("stats"))\nprint(Prefs.str("routing"))\nprecondition(Prefs.set("tips", false))\n')
            compiled = subprocess.run(['swiftc', str(file), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            cases = [({}, 'balanced'), ({'escalate': False}, 'cheapest'),
                     ({'escalateAuto': False}, 'cheapest'), ({'model': 'sonnet'}, 'capable'),
                     ({'model': 'opus', 'escalate': False}, 'capable'),
                     ({'routing': 'balanced', 'model': 'opus'}, 'balanced'),
                     ({'routing': 'cheapest', 'model': 'opus'}, 'cheapest')]
            for values, expected in cases:
                with self.subTest(values=values):
                    state = root / 'settings.json'; state.write_text(json.dumps(values))
                    result = subprocess.run([str(binary)], env={**os.environ, 'ATTICUS_DIR': str(root)}, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)
                    self.assertEqual(json.loads(state.read_text())['routing'], expected)

    def test_voice_setting_bridge_accepts_migrated_choices(self):
        source = (ROOT / 'Atticus.swift').read_text()
        prefs = source[source.index('enum Prefs {'):source.index('\nfunc applySharing')]
        start = source.index('                        if p.count == 3, Prefs.defaults[')
        bridge = source[start:source.index('\n                        continue', start)]
        fixture = '''
final class Settings {
    func apply(_ key: String, _ value: Any) { precondition(Prefs.set(key, value)) }
    func push() {}
}
enum Atticus { static let settings = Settings() }
let p = ["⚙", "routing", "capable"]
''' + bridge + '\nprecondition(Prefs.str("routing") == "capable", "Voice choice was ignored")\n'
        with tempfile.TemporaryDirectory() as tmp:
            file, binary = Path(tmp) / 'bridge.swift', Path(tmp) / 'bridge'
            file.write_text('import Foundation\nlet controlKey = 1, optionKey = 2\n' + prefs + fixture)
            result = subprocess.run(['swiftc', str(file), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], env={**os.environ, 'ATTICUS_DIR': tmp}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((Path(tmp) / 'settings.json').read_text())['routing'], 'capable')
