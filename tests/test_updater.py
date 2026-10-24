import os, re, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = re.search(r'let r = sh\(#"""\n(.*?)"""#\)', (Path(__file__).parent.parent / 'Atticus.swift').read_text(), re.S).group(1)


@unittest.skipUnless(sys.platform == 'darwin', 'the app runs this updater with macOS /bin/zsh')
class UpdaterTests(unittest.TestCase):
    def test_repeated_checks_do_not_start_overlapping_updates(self):
        source = (Path(__file__).parent.parent / 'Atticus.swift').read_text()
        updater = source.split('enum Updater {', 1)[1].split('// Opening Atticus again', 1)[0]
        self.assertIn('guard !checking else { done(); return }', updater)
        self.assertLess(updater.index('checking = true'), updater.index('status = "Checking…"'))
        self.assertIn('DispatchQueue.main.async {\n                checking = false', updater)

    # Oct 21: main was 99 commits ahead of origin; HEAD != @{u} read as an update, so Atticus rebuilt and relaunched every ~90 s.
    def test_only_new_upstream_commits_rebuild(self):
        scratch = tempfile.TemporaryDirectory(); self.addCleanup(scratch.cleanup); root = Path(scratch.name)
        git = lambda cwd, *a: subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@t', *a], check=True, capture_output=True)
        git(root, 'init', '-q', '--bare', 'origin.git'); git(root, 'clone', '-q', 'origin.git', 'src'); src = root / 'src'
        (src / 'build.sh').write_text('#!/bin/sh\ntouch built\n'); os.chmod(src / 'build.sh', 0o755)
        (src / '.gitignore').write_text('built\n'); git(src, 'add', '.'); git(src, 'commit', '-qm', 'one'); git(src, 'push', '-q', 'origin', 'HEAD')
        run = lambda: subprocess.run(['/bin/zsh', '-c', SCRIPT, str(src)], capture_output=True).returncode
        self.assertEqual(run(), 0)
        (src / 'a').write_text('local'); git(src, 'add', 'a'); git(src, 'commit', '-qm', 'unpushed')
        self.assertEqual(run(), 0); self.assertFalse((src / 'built').exists())
        git(root, 'clone', '-q', 'origin.git', 'other'); (root / 'other' / 'b').write_text('new'); git(root / 'other', 'add', 'b')
        git(root / 'other', 'commit', '-qm', 'upstream'); git(root / 'other', 'push', '-q', 'origin', 'HEAD')
        self.assertEqual(run(), 5)   # diverged: --ff-only refuses, the running version stays
        git(src, 'reset', '-q', '--hard', 'HEAD~1')
        self.assertEqual(run(), 10); self.assertTrue((src / 'built').exists())


if __name__ == '__main__':
    unittest.main()
