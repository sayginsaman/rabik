"""Ready to ship: a release opens at login through SMAppService, carries its own Python (checksum pinned, every Mach-O signed)
so Apple silicon Macs need no Command Line Tools, and rabik.py runs that Python when it sits next to it."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard

ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / 'build.sh').read_text()


class ReleaseTests(unittest.TestCase):
    def test_a_release_is_a_login_item_and_a_source_build_keeps_its_launch_agent(self):
        login = (ROOT / 'Sources/Rabik/App/LoginItem.swift').read_text()
        self.assertIn('try SMAppService.mainApp.register()', login)
        self.assertIn('static var fromSource: Bool { Bundle.main.object(forInfoDictionaryKey: "RabikSource") != nil }', login)
        self.assertIn('p.arguments = [on ? "enable" : "disable", "gui/\\(getuid())/com.rabik.app"]', login)
        self.assertIn('LoginItem.firstLaunch()', (ROOT / 'Sources/Rabik/main.swift').read_text())
        self.assertIn('if !LoginItem.set(v as? Bool == true) {', (ROOT / 'Sources/Rabik/Settings/SettingsWindow.swift').read_text())

    def test_the_release_bundles_a_pinned_python_and_signs_every_binary_in_it(self):
        self.assertIn('PY_SHA=11785155d0f70e634178219c20925d8f20be00a3da4684fc4f5019dd15602ef7', BUILD)
        self.assertIn('shasum -a 256 -c -', BUILD)
        self.assertIn('find "$PY" -name __pycache__ -type d -prune -exec rm -rf {} +', BUILD)
        sign_inside, sign_app = BUILD.index('if file -b "$f" | grep -q Mach-O; then codesign --force --options runtime --timestamp'), BUILD.index('--entitlements Rabik.entitlements --sign "$RABIK_SIGN_ID" "$APP"')
        self.assertLess(sign_inside, sign_app)   # inside out

    def test_rabik_py_prefers_the_python_beside_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = Path(tmp) / 'Resources'; (res / 'python' / 'bin').mkdir(parents=True)
            shutil.copy(ROOT / 'rabik.py', res / 'rabik.py')
            fake = res / 'python' / 'bin' / 'python3'
            fake.write_text('#!/bin/sh\necho "bundled $#"\n'); fake.chmod(0o755)
            out = subprocess.run(['/bin/sh', str(res / 'rabik.py'), '--history', 'x'], capture_output=True, text=True, env={**os.environ, 'PATH': '/usr/bin:/bin'})
            self.assertEqual(out.stdout.strip(), 'bundled 5')   # -c, the loader, rabik.py and both arguments
            fake.unlink()
        first = (ROOT / 'rabik.py').read_text().splitlines()[1]
        self.assertTrue(first.startswith('"exec" "$(p=${0%/*}/python/bin/python3; [ -x $p ] && echo $p || echo python3)" "-c"'))   # else python3, as before


    def test_a_release_updates_through_sparkle_and_writes_a_signed_appcast(self):
        updates = (ROOT / 'Sources/Rabik/App/ReleaseUpdates.swift').read_text()
        self.assertIn('#if canImport(Sparkle)', updates)   # a build from source and the checks compile without it
        self.assertIn('SPUStandardUpdaterController(startingUpdater: true', updates)
        self.assertIn('fetch Sparkle-2.10.0.tar.xz https://github.com/sparkle-project/Sparkle/releases/download/2.10.0/Sparkle-2.10.0.tar.xz c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c', BUILD)
        self.assertIn('SU_FEED=https://github.com/sayginsaman/rabik/releases/latest/download/appcast.xml', BUILD)
        self.assertIn('SIG=$("$SPK/bin/sign_update" --ed-key-file "$KEY" "$DMG")', BUILD)
        self.assertIn('if src.isEmpty && ReleaseUpdates.available { ReleaseUpdates.check()', (ROOT / 'Sources/Rabik/App/Updater.swift').read_text())
        self.assertFalse(list(ROOT.rglob('sparkle_ed25519_key')))   # the private key never enters the repo


if __name__ == '__main__':
    unittest.main()
