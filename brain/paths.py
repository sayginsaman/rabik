"""Where Rabik's files are, and the helper's own command lines the model is taught.

ME is the entry script, rabik.py next to this package (inside Rabik.app once built): helper commands, the gate and
saved shortcuts all name that path, so it never points into brain/."""
import os
import plistlib
import re
import shlex
from pathlib import Path

from brain import environ
__all__ = ['HOME', 'DIR', 'ME', 'PLACE', 'LOOK', 'SEARCH', 'READ', 'SHOW', 'REMEMBER', 'FORGET', 'TYPE', 'PLAY', 'QUEUE', 'ABOUT',
           'SHORTCUT', 'FRONT', 'WATCH', 'PICK', 'SET', 'WEB', 'HISTORY', 'HANDS', 'WINDOW', 'ROUTINE', 'DRAW', 'MEMORY',
           'RECENT', 'PREFS', 'REPOSITORY', 'APP_VERSION', 'SHOT', 'APP', 'question_path', 'agent_gate_dir', 'request_file',
           'LAST', 'WORKED', 'hands_state']

HOME = os.path.expanduser('~')
DIR = environ.sandbox_dir() or os.path.join(HOME, '.config/rabik')   # RABIK_DIR: tests keep off the user's chat and rules
ME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rabik.py')   # inside Rabik.app once built, so the AI's helper commands point here
PLACE, LOOK, SEARCH, READ, SHOW, REMEMBER, FORGET, TYPE, PLAY, QUEUE, ABOUT, SHORTCUT, FRONT, WATCH, PICK, SET, WEB, HISTORY, HANDS, WINDOW, ROUTINE = (shlex.quote(ME) + f' --{c}' for c in ('place', 'look', 'search', 'read', 'show', 'remember', 'forget', 'type', 'play', 'queue', 'me add', 'shortcut', 'front', 'watch', 'pick', 'set', 'web', 'history', 'hands', 'window', 'routine'))
DRAW = shlex.quote(ME) + " --draw"
MEMORY, RECENT = os.path.join(DIR, 'memory.md'), os.path.join(DIR, 'recent.jsonl')
PREFS = os.path.join(DIR, 'settings.json')   # written by the Settings window
REPOSITORY = 'https://github.com/sayginsaman/rabik'   # feedback opens a new issue here; keep `repository` in Sources/Rabik/main.swift the same
try:
    APP_VERSION = Path(ME).with_name('VERSION').read_text().strip()
except OSError:
    try:
        with open(Path(ME).parents[1] / 'Info.plist', 'rb') as f: APP_VERSION = plistlib.load(f).get('CFBundleShortVersionString', 'unknown')
    except (OSError, ValueError): APP_VERSION = 'unknown'
SHOT = '/tmp/rabik-screen'   # + -<n>.jpg, one per display
APP = environ.app() or os.path.join(HOME, 'Applications/Rabik.app/Contents/MacOS/Rabik')   # set by Rabik.app


def question_path(directory):
    """This ask's pending card. Cards and answers live in DIR, not the ask folder: a sandboxed command can write
    there, and must never reword a card or answer its own Allow."""
    return os.path.join(DIR, 'answers', os.path.basename(os.path.normpath(directory)) + '.q')


def agent_gate_dir(directory):
    identifier = os.path.basename(directory)
    return os.path.join(DIR, 'agent-gates', identifier) if re.fullmatch(r'[a-f0-9]{32}', identifier) else directory


def request_file(directory):
    """The user's own words for this ask. Memory, password typing and focus trust them, so they live where no sandbox writes:
    an agent's gate folder, or DIR/answers beside the ask's Allow card (the ask folder itself is in the writable $TMPDIR)."""
    gate = agent_gate_dir(directory)
    return os.path.join(gate, 'request') if gate != directory else question_path(directory)[:-2] + '.request'


LAST = os.path.join(DIR, 'last_app')


WORKED = os.path.join(DIR, 'worked.json')   # the window the last task worked in (mini screen target)


def hands_state():
    return environ.hands_file(os.path.join(DIR, 'hands.json'))
