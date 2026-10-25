"""The Mac around an ask: AppleScript, screens, the front app, focus kept with the user, and the work window the box
shows (▣)."""
import json
import os
import re
import shlex
import subprocess
from brain import paths, prefs, protocol, turn

__all__ = ['osa', 'osa_quote', 'wants_focus', 'asks_front', 'screens', 'describe', 'front', 'free_focus', 'allow_focus',
           'restore_focus', 'request_screen', 'window_target', 'cached_hands', 'preview_app', 'preview_commands']


def osa(script, *args, timeout=60):
    try: return subprocess.run(['osascript', '-e', script, *args], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except subprocess.TimeoutExpired: return ''   # a stuck Apple event must not hang the ask


def osa_quote(text):
    """Text for inside an AppleScript "…" literal: a model- or page-supplied name must never end the string and run code."""
    return str(text).replace('\\', '\\\\').replace('"', '\\"')


def wants_focus(task=None, sites=False):
    ask = os.environ.get('RABIK_ASK')
    if os.environ.get('RABIK_AGENT') and not sites:   # agents stay behind unless the user's own words asked for front work
        return bool(ask) and os.path.exists(os.path.join(paths.agent_gate_dir(ask), 'focus-requested'))
    if ask and os.path.exists(os.path.join(ask, 'focus-requested')): return True
    if task is None:
        task = os.environ.get('RABIK_REQUEST', '')
        if ask:
            try:
                with open(paths.request_file(ask)) as f: task = f.read()
            except OSError: pass
    if re.search(r'\b(background|behind)\b', task, re.I): return False
    return sites or asks_front(task)


def asks_front(task):
    return not re.search(r'\b(background|behind)\b', task, re.I) and any(
        (m[1].lower() != 'open' or re.match(r'\s+\w', task[m.end():]) and not re.search(r'\b(is|are|was|were|be|already)\s*$', task[:m.start()], re.I)) and
        not re.search(r"\b(don.t|do not|never|without|avoid|no need to)\b[^,;.]*$", task[:m.start()].rsplit(' but ', 1)[-1], re.I)
        for m in re.finditer(r'\b(open|show|switch to|focus|bring up|bring .{0,40}forward|full ?screen|foreground|in front)\b', task, re.I))


def preview_app(app, action='work', title='', directory=None, frame=None):
    if not app or os.environ.get('RABIK_LIVE') == '1' and prefs.pref('workIn', 'back') != 'front' and not wants_focus(): return
    try:
        mapped = cached_hands() if frame is None and not title and os.environ.get('RABIK_HANDS_STATE') else None
        if isinstance(mapped, dict) and str(mapped.get('app', '')).casefold() == str(app).casefold():
            pinned = mapped.get('windowFrame')
            if isinstance(pinned, list) and len(pinned) == 4: frame = pinned
        r = subprocess.run([paths.APP, '--window-target', app, title] + ([json.dumps(frame)] if frame else []), capture_output=True, text=True, timeout=2,
                           env={**os.environ, 'RABIK_FOCUS_REQUESTED': '1' if wants_focus() else '0'})
        if r.returncode or not r.stdout.strip(): return
        target = json.loads(r.stdout)
        protocol.emit(['▣ ' + json.dumps({**target, 'action': action})], directory)
        return target
    except (OSError, ValueError, subprocess.TimeoutExpired): pass


def window_target(app, title=''):
    """The app's window (title words): id, frame, minimized, and visible (on a display, uncovered); {} if none. Never activates."""
    try:
        r = subprocess.run([paths.APP, '--window-target', app, title], capture_output=True, text=True, timeout=2, env={**os.environ, 'RABIK_FOCUS_REQUESTED': '0'})
        target = json.loads(r.stdout)
        return target if isinstance(target, dict) and str(target.get('windowID', '')).isdigit() else {}
    except (OSError, ValueError, subprocess.TimeoutExpired): return {}


def preview_commands(cmd, directory=None):
    apps = re.findall(r'(?:tell (?:application(?: id)?|app|process)|process)\s+"([^"]+)"', cmd, re.I)
    title = next(iter(re.findall(r'(?:name (?:contains|is)|window)\s+"([^"]+)"', cmd, re.I)), '')
    for app in dict.fromkeys(apps):
        if app != 'System Events': preview_app(app, title=title, directory=directory)
    try: tokens = shlex.split(cmd)
    except ValueError: return
    for i, token in enumerate(tokens):
        if os.path.basename(token) != 'open': continue
        args = tokens[i + 1:]
        if '-a' in args:
            at = args.index('-a') + 1
            if at < len(args): preview_app(args[at], 'open', directory=directory)
        else:
            target = next((arg for arg in args if not arg.startswith('-')), '')
            if target: preview_app(os.path.expanduser(target), 'open', directory=directory)


def screens():
    """[(name, x, y, w, h, built_in)], top-left coordinates like System Events uses; the first is the main one.
    built_in comes from macOS itself, so laptop vs monitor works on any Mac, any number of displays."""
    out = subprocess.run(['osascript', '-l', 'JavaScript', '-e', 'ObjC.import("AppKit"); ObjC.bindFunction("CGDisplayIsBuiltin", ["bool", ["unsigned int"]]); '
        'var s=$.NSScreen.screens.js, H=s[0].frame.size.height; JSON.stringify(s.map(x=>[x.localizedName.js, x.frame.origin.x, '
        'H-x.frame.origin.y-x.frame.size.height, x.frame.size.width, x.frame.size.height, '
        '$.CGDisplayIsBuiltin(ObjC.unwrap(x.deviceDescription.objectForKey("NSScreenNumber")))]))'],
        capture_output=True, text=True).stdout
    try: rows = json.loads(out)
    except ValueError: return []
    if not isinstance(rows, list): return []
    try: return [(n, int(x), int(y), int(w), int(h), bool(b)) for n, x, y, w, h, b in rows if isinstance(n, str)]
    except (TypeError, ValueError, OverflowError): return []


def describe(scr, fx=None, fy=None):
    """The screens in words for the AI: kind, size, where each sits, which one the user is on."""
    if not scr: return "Display information unavailable"
    mx, my = scr[0][1], scr[0][2]
    def spot(s):
        if s is scr[0]:
            return 'main'
        return ('left of main' if s[1] + s[3] <= mx else 'right of main' if s[1] >= mx + scr[0][3] else
                'above main' if s[2] + s[4] <= my else 'below main')
    on = next((s for s in scr if fx is not None and s[1] <= fx < s[1] + s[3]
               and (fy is None or s[2] <= fy < s[2] + s[4])), None)
    return '; '.join(f'"{s[0]}" ({"built-in laptop screen" if s[5] else "external monitor"}, {s[3]}x{s[4]}, {spot(s)}, x={s[1]} y={s[2]}'
                     + (', the front window is here' if s is on else '') + ')' for s in scr)


def front():
    # Rabik.app passes the app the user was in when the user pressed the keys (its own windows can take focus, e.g. onboarding)
    app = os.environ.get('RABIK_FRONT') or osa('tell application "System Events" to get name of first process whose frontmost is true')
    return app, osa(f'tell application "System Events" to tell process "{app}" to get name of front window') if app else ''   # no front app: nothing to ask


def free_focus(user=False):
    """Rabik.app's focus guard stands aside for 3 s: a move or full screen brings the app forward on purpose. Short, so a later
    background step (Spotify starting) still stays behind."""
    try: subprocess.run([paths.APP, '--raise'] + (['user'] if user else []), capture_output=True, timeout=1)
    except (OSError, subprocess.TimeoutExpired): pass


def allow_focus(task):
    if wants_focus(task) or prefs.pref('workIn', 'back') == 'front':
        free_focus(user=True)


def restore_focus(app, task, cmds):
    if wants_focus(task) or re.search(r'\b(close|quit|exit)\b', task, re.I) or prefs.pref('workIn', 'back') == 'front':
        return
    now = osa('tell application "System Events" to get name of first process whose frontmost is true')
    try:   # written during this ask only; an earlier task's window is not one this task touched
        with open(paths.WORKED) as f: worked = json.load(f).get('app', '') if os.path.getmtime(paths.WORKED) >= turn.TURN.get('_started', 0) else ''
    except (OSError, ValueError, AttributeError): worked = ''
    # only an app this task touched (named in a command: tell, open -a, process; or the window it worked in), never one the user switched to
    if not now or now == app or not (now.lower() in ' '.join(cmds).lower() or now == worked): return
    # Address a running process, never `activate` an app: that can relaunch it or reopen its closed window.
    osa('on run argv\ntell application "System Events"\n'
        'if exists process (item 1 of argv) then\nset frontmost of process (item 1 of argv) to true\n'
        'end if\nend tell\nend run', app)


def request_screen():
    if os.environ.get('RABIK_SCREEN'): return os.environ['RABIK_SCREEN']
    app = os.environ.get('RABIK_FRONT') or front()[0]
    try:
        x, y = map(int, osa(f'tell application "System Events" to tell process "{app}" to get position of window 1').split(', '))
        return next((n for n, sx, sy, w, h, _ in screens() if sx <= x + 50 < sx + w and sy <= y + 50 < sy + h), 'current')
    except ValueError: return 'current'


def cached_hands():
    try:
        with open(paths.hands_state()) as f: return json.load(f)
    except (OSError, ValueError): return None
