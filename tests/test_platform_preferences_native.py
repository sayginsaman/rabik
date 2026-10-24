"""Opt-in VM integration for the platform preferences UI; never run on the host."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin" and
                     (os.environ.get("ATTICUS_SYSTEM_UI_TEST") == "1" or any("test_platform_preferences_native" in arg for arg in sys.argv)),
                     "explicit VM integration")
class PlatformPreferencesTests(unittest.TestCase):
    def test_rows_and_switches_resolve_by_accessible_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "Fixture.app"
            binary = app / "Contents/MacOS/Fixture"
            binary.parent.mkdir(parents=True)
            (app / "Contents/Info.plist").write_text(
                '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
                '<key>CFBundleIdentifier</key><string>com.atticus.app</string>'
                '<key>CFBundleExecutable</key><string>Fixture</string>'
                '<key>CFBundlePackageType</key><string>APPL</string></dict></plist>'
            )
            compiled = subprocess.run(["swiftc", "-O", "-module-name", "Atticus", str(ROOT / "Atticus.swift"), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            state = root / "hands.json"
            env = {**os.environ, "ATTICUS_DIR": str(root), "ATTICUS_HANDS_STATE": str(state), "ATTICUS_HANDS_TIMING": "1"}
            (root / "settings.json").write_text('{"safe":false}')
            subprocess.run(["open", "x-apple.systempreferences:"], check=True)

            def call(*args, receipt=None):
                return subprocess.run(
                    [str(binary), "--hands", *args],
                    input=json.dumps(receipt) if receipt else None,
                    env={**env, "ATTICUS_HANDS_RECEIPT": "1" if receipt else "0"},
                    capture_output=True, text=True, timeout=5,
                )

            end = time.monotonic() + 8
            seen = None
            while time.monotonic() < end:
                seen = call("see")
                if seen.returncode == 0:
                    break
                time.sleep(.1)
            if not seen or "Allow Atticus" in seen.stdout:
                self.skipTest("temporary bundle lacks VM accessibility permission")
            self.assertEqual(seen.returncode, 0, seen.stdout + seen.stderr)
            mapped = json.loads(state.read_text())
            rows = [node for node in mapped["nodes"] if node["role"] in ("AXRow", "AXCell") and node["label"]]
            self.assertTrue(rows, seen.stdout)

            def act(verb, target):
                checked = call("label", verb, target)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                receipt = json.loads(checked.stdout)
                done = call(verb, target, receipt=receipt)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                return done

            started = time.perf_counter()
            switches, visited = [], set()
            for _ in range(16):
                rows = [node for node in mapped["nodes"] if node["role"] in ("AXRow", "AXCell") and node["label"] not in visited]
                if not rows:
                    break
                visited.add(rows[0]["label"])
                act("click", rows[0]["label"])
                refreshed = call("see")
                self.assertEqual(refreshed.returncode, 0, refreshed.stdout + refreshed.stderr)
                mapped = json.loads(state.read_text())
                switches = [node for node in mapped["nodes"] if node["role"] in ("AXCheckBox", "AXSwitch") and node["label"]]
                if switches:
                    break
            if not switches:
                self.skipTest("the discovered pane exposes no reversible switch")
            switch = switches[0]
            before = switch["value"]
            act("click", switch["label"])
            changed = json.loads(state.read_text())
            after = next(node["value"] for node in changed["nodes"] if node["role"] == switch["role"] and node["label"] == switch["label"])
            self.assertNotEqual(after, before)
            act("click", switch["label"])
            restored = json.loads(state.read_text())
            final = next(node["value"] for node in restored["nodes"] if node["role"] == switch["role"] and node["label"] == switch["label"])
            self.assertEqual(final, before)
            print(f"PLATFORM TOGGLE VERIFIED: {(time.perf_counter() - started):.3f}s", flush=True)


if __name__ == "__main__":
    unittest.main()
