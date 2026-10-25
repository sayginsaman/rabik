"""Isolate config before importing any Rabik test module."""
import atexit
import os
import shutil
import tempfile

config = tempfile.TemporaryDirectory(prefix='rabik-test-config-')
os.environ['RABIK_DIR'] = config.name
os.environ['RABIK_POSTHOG_KEY'] = ''   # tests that clear os.environ also drop RABIK_DIR; with no key nothing reaches PostHog
atexit.register(config.cleanup)


def scratch_dir(test):
    """A temp rabik.DIR with default prefs for one test, undone at cleanup; returns the folder."""
    from pathlib import Path
    from unittest.mock import patch
    import rabik
    root = tempfile.TemporaryDirectory(); test.addCleanup(root.cleanup)
    for p in (patch.object(rabik, 'DIR', root.name), patch.object(rabik, 'pref', side_effect=lambda k, d: d)):
        p.start(); test.addCleanup(p.stop)
    return Path(root.name)


# Every ask pays for the system prompt. Budgets measure it with one typical installed helper path, so a long checkout or
# home folder, or a space that makes the path shell-quoted, can neither fail nor pass a budget by accident.
INSTALLED_HELPER = '/Users/exampleuser/Applications/Rabik.app/Contents/Resources/rabik.py'


def prompt_chars(text):
    import shlex
    import rabik
    return len(text.replace(shlex.quote(rabik.ME), INSTALLED_HELPER).replace(rabik.ME, INSTALLED_HELPER))


def run_swift(test, source, timeout=10):
    """Compile Swift source to a temp binary, run it, assert both succeed; returns its stdout."""
    import subprocess, sys
    from pathlib import Path
    if sys.platform != 'darwin': test.skipTest('needs macOS frameworks (Cocoa, AppKit)')
    with tempfile.TemporaryDirectory() as root:
        path, binary = Path(root) / 'test.swift', Path(root) / 'test'
        path.write_text(source)
        result = subprocess.run(['swiftc', str(path), '-o', str(binary)], capture_output=True, text=True)
        test.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=timeout)
        test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout


import subprocess
import unittest

_popen_init = subprocess.Popen.__init__
_tmp = os.path.realpath(tempfile.gettempdir())
AI_CLIENTS = ('claude', 'devin', 'pi')
LAUNCHED = []   # real AI clients a test started; test_zz_host_guard fails the run if any, even from a thread


class RealClientLaunched(BaseException):
    """A BaseException, so rabik's `except Exception` handlers cannot swallow it: a test whose mocks stopped applying fails."""


def _guarded(self, args, *a, **k):
    first = args if isinstance(args, (str, bytes, os.PathLike)) else (args[0] if args else '')
    given = str(first).split()[0] if first else ''
    exe = os.path.realpath(given) if given else ''
    name = os.path.basename(exe)
    # A fake client a test made under the temp folder is fine; the user's installed one (often a symlink into a versions folder)
    # never is. A bare name runs whatever the child's PATH finds first, so judge that file.
    found = given if '/' in given else shutil.which(given, path=(k.get('env') or os.environ).get('PATH')) if given else None
    real = os.path.realpath(found) if found else ''
    if found and (os.path.basename(given) in AI_CLIENTS or os.path.basename(real) in AI_CLIENTS or '/claude/versions/' in real) \
            and not real.startswith(_tmp):
        LAUNCHED.append(given)
        raise RealClientLaunched(f'test started the real AI client {given}; mock it or use a fake under the temp folder')
    # Host guard: window/app-driving tests run only in the VM (run.sh sets RABIK_VM=1). On a developer's Mac, launching a
    # compiled fixture/harness, osascript, `open`, screencapture or the Rabik binary skips the test instead of taking over the screen.
    if not os.environ.get('RABIK_VM') and not os.environ.get('RABIK_ALLOW_HOST_UI') and (
            exe.startswith(_tmp) or name in ('osascript', 'open', 'screencapture', 'Rabik', 'swift') or '/Rabik.app/' in exe):
        raise unittest.SkipTest(f'host guard: {name} runs only in the VM (run.sh)')
    _popen_init(self, args, *a, **k)
subprocess.Popen.__init__ = _guarded


# The app runs one ask per process. A test's in-process rabik.main() left its ask folder, env and relay thread behind;
# the relay polls time.sleep until the folder goes, so a later test's fake clock or sleep mock counted its naps.
import rabik
_main = rabik.main


def _one_ask(*a, **k):
    env = dict(os.environ)
    try:
        return _main(*a, **k)
    finally:
        state = os.path.dirname(os.environ.get('RABIK_HANDS_STATE', ''))
        if os.environ.get('RABIK_HANDS_STATE') != env.get('RABIK_HANDS_STATE') and os.path.basename(state).startswith('rabik-hands-'):
            shutil.rmtree(state, True)
        os.environ.clear(); os.environ.update(env)
rabik.main = _one_ask
