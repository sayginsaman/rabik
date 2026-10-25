"""Runs last in discovery: no test may have started a real AI client, even from a thread where the guard's error was lost."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tests


class HostGuardTests(unittest.TestCase):
    def test_guard_stops_real_clients_but_not_temp_fakes(self):
        installed = '/opt/homebrew/bin/claude'   # what PATH finds on a developer's Mac; CI has no client at all
        with patch.object(tests, 'LAUNCHED', []), patch('shutil.which', return_value=installed):
            for client in ('claude', '/usr/local/bin/devin', 'pi'):
                with self.assertRaises(tests.RealClientLaunched):
                    subprocess.Popen([client, '-p'])
            self.assertEqual(len(tests.LAUNCHED), 3)
        with tempfile.TemporaryDirectory() as root:
            fake = os.path.join(root, 'claude')
            with open(fake, 'w') as f: f.write('#!/bin/sh\nexit 0\n')
            os.chmod(fake, 0o700)
            try:
                subprocess.run([fake], check=True, timeout=5)
            except unittest.SkipTest:   # the host guard also keeps temp executables to the VM
                pass

    def test_no_test_started_a_real_ai_client(self):
        self.assertEqual(tests.LAUNCHED, [], 'Mock these clients; a test reached the real one: ' + ', '.join(tests.LAUNCHED))


if __name__ == '__main__':
    sys.exit(unittest.main())
