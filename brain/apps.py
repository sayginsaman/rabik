"""Installed and running apps: names as the user says them, process names and bundle IDs, quitting, waiting for a launch.

_APPS_CACHE is rebound when it refreshes, so it is not in __all__: rabik.py's facade reads it here, live."""
import difflib
import os
import plistlib
import re
import subprocess
import time
from pathlib import Path
from brain import macos, paths, wording

__all__ = ['installed_apps', 'app_words', 'default_browser', 'app_named', 'app_heard', 'proc_of', 'app_id', 'app_running', 'quit_app', 'app_up']


_APPS_CACHE = (0.0, set())


def installed_apps():
    global _APPS_CACHE
    if _APPS_CACHE[0] and time.monotonic() - _APPS_CACHE[0] < 3600:
        return _APPS_CACHE[1]
    fallback = {f[:-4] for d in ('/Applications', '/System/Applications', '/System/Applications/Utilities', '/System/Library/CoreServices', paths.HOME + '/Applications')
                if os.path.isdir(d) for f in os.listdir(d) if f.endswith('.app')}
    try:
        search = subprocess.Popen(['mdfind', 'kMDItemContentType == "com.apple.application-bundle"'],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        found, _ = search.communicate(timeout=.08)
        apps = {Path(path).stem for path in (found or '').splitlines() if path.rstrip('/').endswith('.app')} if not search.returncode else set()
    except subprocess.TimeoutExpired:
        search.kill(); search.communicate()
        apps = set()
    except OSError:
        apps = set()
    _APPS_CACHE = (time.monotonic() if apps else time.monotonic() - 3595, apps | fallback)
    return _APPS_CACHE[1]


def app_words(words):
    """ "the Notes app" -> "notes" """
    return re.sub(r'\s+(app|application)$', '', words.lower().strip(' .!?').removeprefix('the ').removeprefix('my '))


def default_browser():
    """The app macOS opens web links with (System Settings → Desktop & Dock → Default web browser); Safari if none was picked."""
    try:
        with open(os.path.join(paths.HOME, 'Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist'), 'rb') as f:
            saved = plistlib.load(f)
    except (OSError, ValueError):
        saved = {}
    handlers = saved.get('LSHandlers', []) if isinstance(saved, dict) else []
    bid = next((h.get('LSHandlerRoleAll') for h in handlers if isinstance(h, dict) and h.get('LSHandlerURLScheme') == 'https'), None)
    return isinstance(bid, str) and macos.osa(f'name of application id "{macos.osa_quote(bid)}"') or 'Safari'


def app_named(words):
    """Spoken name -> installed app name, or None. Whole-name matches only, so "chrome history" is not Chrome."""
    w = app_words(words)
    if w in ('browser', 'web browser', 'internet browser'): return default_browser()   # "my browser" is the one links open in, never Tor Browser by its last word
    key = lambda n: re.sub(r'[^a-z0-9]', '', n.lower())   # "trading view" = "TradingView"
    apps = installed_apps()
    exact = [a for a in apps if key(a) == key(w)]
    if len(exact) == 1: return exact[0]
    matches = [a for a in apps if key(a.split()[-1]) == key(w) or key(''.join(p[0] for p in a.split()[:-1]) + a.split()[-1]) == key(w)]
    return matches[0] if len(matches) == 1 else None


def app_heard(words):
    """A misheard app name -> the one installed app spelled close to it with the same first sound ("Ascidian" -> Obsidian), or None.
    Only for "open X": a near miss there opens an app, it never replays or quits one."""
    words = app_words(words)
    w = re.sub(r'[^a-z0-9]', '', words)
    if len(w) < 3 or len(words.split()) > 3: return None
    def score(app):   # its whole name or last word ("Google Chrome" -> chrome); "gmail" never opens Mail, "spotify web" is more than Spotify
        names = {re.sub(r'[^a-z0-9]', '', n.lower()) for n in (app, app.split()[-1])}
        return max((difflib.SequenceMatcher(None, w, n).ratio() for n in names if n and n not in w and wording.dictate_sound(n)[:1] == wording.dictate_sound(w)[:1]), default=0)
    ranked = sorted(((score(a), a) for a in installed_apps()), reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] >= .75 and (len(ranked) < 2 or ranked[1][0] < ranked[0][0]) else None


def proc_of(app):
    """App name -> its System Events process name (Visual Studio Code runs as "Code")."""
    bid = macos.osa(f'id of application "{macos.osa_quote(app)}"')
    return macos.osa(f'tell application "System Events" to get name of first process whose bundle identifier is "{macos.osa_quote(bid)}"') or app


def app_id(app):
    return macos.osa(f'id of application "{macos.osa_quote(app)}"')


def app_running(bid):
    return macos.osa(f'tell application "System Events" to exists (first process whose bundle identifier is "{macos.osa_quote(bid)}")') == 'true'


def quit_app(bid):
    """Quit and verify one running app by bundle id; a save dialog may keep it open."""
    if not app_running(bid):
        return True
    macos.osa(f'tell application id "{macos.osa_quote(bid)}" to quit', timeout=2)
    for _ in range(10):
        if not app_running(bid):
            return True
        time.sleep(0.1)
    return False


def app_up(bid):
    """A just-opened app by bundle id: running within 2 s."""
    for _ in range(20):
        if app_running(bid):
            return True
        time.sleep(0.1)
    return False
