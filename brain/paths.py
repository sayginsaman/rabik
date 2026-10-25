"""Where Rabik's files are, and the helper's own command lines the model is taught.

ME is the entry script, rabik.py next to this package (inside Rabik.app once built): helper commands, the gate and
saved shortcuts all name that path, so it never points into brain/."""
import os
import plistlib
import shlex
from pathlib import Path

__all__ = ['HOME', 'DIR', 'ME', 'PLACE', 'LOOK', 'SEARCH', 'READ', 'SHOW', 'REMEMBER', 'FORGET', 'TYPE', 'PLAY', 'QUEUE', 'ABOUT',
           'SHORTCUT', 'FRONT', 'WATCH', 'PICK', 'SET', 'WEB', 'HISTORY', 'HANDS', 'WINDOW', 'ROUTINE', 'DRAW', 'MEMORY', 'RECENT', 'PREFS',
           'REPOSITORY', 'APP_VERSION', 'SHOT', 'APP']

HOME = os.path.expanduser('~')
DIR = os.environ.get('RABIK_DIR') or os.path.join(HOME, '.config/rabik')   # RABIK_DIR: tests keep off the user's chat and rules
ME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rabik.py')   # inside Rabik.app once built, so the AI's helper commands point here
PLACE, LOOK, SEARCH, READ, SHOW, REMEMBER, FORGET, TYPE, PLAY, QUEUE, ABOUT, SHORTCUT, FRONT, WATCH, PICK, SET, WEB, HISTORY, HANDS, WINDOW, ROUTINE = (shlex.quote(ME) + f' --{c}' for c in ('place', 'look', 'search', 'read', 'show', 'remember', 'forget', 'type', 'play', 'queue', 'me add', 'shortcut', 'front', 'watch', 'pick', 'set', 'web', 'history', 'hands', 'window', 'routine'))
DRAW = shlex.quote(ME) + " --draw"
MEMORY, RECENT = os.path.join(DIR, 'memory.md'), os.path.join(DIR, 'recent.jsonl')
PREFS = os.path.join(DIR, 'settings.json')   # written by the Settings window
REPOSITORY = 'https://github.com/YOUR_GITHUB/rabik'   # feedback opens a new issue here; keep Rabik.swift's `repository` the same
try:
    APP_VERSION = Path(ME).with_name('VERSION').read_text().strip()
except OSError:
    try:
        with open(Path(ME).parents[1] / 'Info.plist', 'rb') as f: APP_VERSION = plistlib.load(f).get('CFBundleShortVersionString', 'unknown')
    except (OSError, ValueError): APP_VERSION = 'unknown'
SHOT = '/tmp/rabik-screen'   # + -<n>.jpg, one per display
APP = os.environ.get('RABIK_APP') or os.path.join(HOME, 'Applications/Rabik.app/Contents/MacOS/Rabik')   # set by Rabik.app
