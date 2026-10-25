"""Window placement (--place) on the laptop, a monitor or the current screen, and spoken moves ("notes on the left of my
monitor")."""
import os
import re
import subprocess
import time
from pathlib import Path
from brain import apps, macos, paths, prefs

__all__ = ['place', 'place_many', 'model_note', 'place_failed', 'keep_behind', 'MOVE_WORDS', 'move_target']


def place(proc, where='full', screen='current', title=''):
    """Place a window; full maximizes, fullscreen enters a native macOS Space."""
    native = where == 'fullscreen'
    if native: where = 'full'
    if where not in ('left', 'right', 'full', 'center'):
        return 'where must be left, right, full, fullscreen or center'
    if screen == 'current': screen = macos.request_screen()
    title = re.sub(r'\.[a-z0-9]{2,4}$', '', title, flags=re.I)   # "notes.pdf" must find a window titled "notes" (macOS hides extensions)
    app_q, title_q = macos.osa_quote(proc), macos.osa_quote(title)
    # the real window: Chrome's window 1 can be a hidden popup bar
    win = f'(first window whose name contains "{title_q}")' if title else '(first window whose subrole is "AXStandardWindow")'
    aw = f'(first window whose name contains "{title_q}")' if title else 'window 1'   # never just the front window when a title was given
    tell = f'tell application "System Events" to tell process "{app_q}" to '
    macos.free_focus()   # moving and full screen bring the app forward; the guard must not put it back mid-move
    pick = {'laptop': lambda s: s[5], 'monitor': lambda s: not s[5]}.get(
        screen, (lambda s: s[0] == screen) if screen != 'current' else (lambda s: s[1] <= px + ww // 2 < s[1] + s[3] and s[2] <= py + wh // 2 < s[2] + s[4]))
    for tries in range(4):   # a window just opened (--show right before) can take a moment to appear
        # full screen (or split view) windows can't move; checked each try, since it only shows once the app is forward
        state = macos.osa(tell + f'tell {win} to return {{value of attribute "AXFullScreen", value of attribute "AXMinimized", position, size}}').split(', ')
        if state[:1] == ['true']:
            try:   # already full screen where it should be: leaving and re-entering is a slow animation for nothing
                fx, fy = map(int, macos.osa(tell + f'get position of {win}').split(', ')); fw, fh = map(int, macos.osa(tell + f'get size of {win}').split(', '))
                there = next((s for s in macos.screens() if pick(s)), None) if where == 'full' and screen != 'current' else None
                if there and there[1] <= fx + fw // 2 < there[1] + there[3]:   # already there, but its full screen Space may not be the one showing: show it
                    macos.free_focus(); macos.osa(tell + f'perform action "AXRaise" of {win}'); subprocess.run(['open', '-a', proc], capture_output=True)
                    return f'{proc} is already full screen on {there[0]}; brought it into view'
            except ValueError: pass
            macos.osa(tell + f'set value of attribute "AXFullScreen" of {win} to false')
            time.sleep(1.2)   # the exit animation
            macos.free_focus()
        try:
            if state[1:2] == ['true']:   # a minimized window moves but stays hidden
                macos.osa(tell + f'set value of attribute "AXMinimized" of {win} to false'); time.sleep(0.4)
            if state[:1] == ['true']:   # bounds changed during the full-screen exit
                state = macos.osa(tell + f'tell {win} to return {{value of attribute "AXFullScreen", value of attribute "AXMinimized", position, size}}').split(', ')
            px, py, ww, wh = map(int, state[2:])
            app_mode = False
            break
        except ValueError:   # System Events can't see it (another Space): scriptable apps (Notes, Finder…) answer for their own windows, fast
            if tries == 0 and macos.osa(f'tell application "System Events" to exists process "{app_q}"') == 'true':
                # its window is on another Space (often its own full screen one): arranging windows is visible work, so bring it here and look again
                subprocess.run(['open', '-a', proc], capture_output=True); time.sleep(0.8)
                continue
            try:
                l, t, r, b = map(int, macos.osa(f'tell application "{app_q}" to get bounds of {aw}').split(', '))
                px, py, ww, wh, app_mode = l, t, r - l, b - t, True
                break
            except ValueError:   # retry a launch without taking the user's focus
                if tries < 3:
                    time.sleep(0.4)
    else:
        return f'no window found for "{proc}" {title}'
    scr = macos.screens()
    n, x, y, w, h, _ = next((s for s in scr if pick(s)), scr[0])
    y, h = y + 25, h - 25   # menu bar
    cw, ch = min(ww, w), min(wh, h)
    bx, by, bw, bh = {'left': (x, y, w // 2, h), 'right': (x + w // 2, y, w - w // 2, h), 'full': (x, y, w, h),
                      'center': (x + (w - cw) // 2, y + (h - ch) // 2, cw, ch)}[where]
    # One step via the app when it is scriptable (Finder, Safari, Chrome…): after a window moves to the other
    # display, System Events often can't see it any more, so a later resize would miss.
    one = f'tell application "{app_q}" to set bounds of {aw} to {{{bx}, {by}, {bx + bw}, {by + bh}}}'
    macos.free_focus()
    if native or (title and not app_mode) or subprocess.run(['osascript', '-e', one], capture_output=True).returncode:
        macos.osa(tell + f'set size of {win} to {{{bw}, {bh}}}')   # size first, then move, then size again
        macos.osa(tell + f'set position of {win} to {{{bx}, {by}}}')
        macos.osa(tell + f'set size of {win} to {{{bw}, {bh}}}')
    def bounds(app_bounds=app_mode):
        for attempt in range(6):   # Accessibility can disappear during a display/full-screen animation
            try:
                if app_bounds:
                    return tuple(map(int, macos.osa(f'tell application "{app_q}" to get bounds of {aw}').split(', ')))
                l, t, r, b = map(int, macos.osa(tell + f'tell {win} to return {{position, size}}').split(', '))
                return l, t, l + r, t + b
            except ValueError:
                if attempt < 5: time.sleep(.2)
        return None
    landed = bounds()   # check, never assume: a window in its own full screen Space or a refused move stays put
    if not landed and not native:
        return f'Moved {proc}, but could not check where its window is. Look at the screen before saying it worked.'
    if landed and not (x <= (landed[0] + landed[2]) // 2 < x + w and y - 25 <= (landed[1] + landed[3]) // 2 < y + h):
        return f'NOT DONE: {proc} window did not move to {n} (it may be full screen in its own Space). Say so; do not report success.'
    if native:
        def entered():
            for _ in range(15):
                if macos.osa(tell + f'get value of attribute "AXFullScreen" of {win}') == 'true': return True
                time.sleep(.1)
        for _ in range(2):   # a request made during another Space animation is dropped: ask once more
            macos.osa(tell + f'set value of attribute "AXFullScreen" of {win} to true')
            if entered(): break
        else: return f'NOT DONE: {proc} did not enter full screen on {n}.'
        landed = None
        for _ in range(15):   # the animation moves the window: judge its display once it holds still, which also lets the next one start
            before, landed = landed, bounds(False)
            if not landed or landed == before: break
            time.sleep(.1)
        if not landed:
            macos.preview_app(proc, 'move', title)
            return f'Moved {proc} into full screen, but could not check which display it used. Look at the screen before saying where it is.'
        l, t, r, b = landed
        if not (x <= (l + r) // 2 < x + w and y - 25 <= (t + b) // 2 < y + h):
            return f'NOT DONE: {proc} entered full screen on the wrong display.'
    macos.preview_app(proc, 'move', title)
    return f'{proc} window -> {"fullscreen" if native else where} of {n}'


def place_many(args):
    from concurrent.futures import ThreadPoolExecutor
    moves = [m.split('\0') for m in '\0'.join(args).split('\0+\0') if m and m != '+']
    if not moves: return 'no window found: no placement requested'
    screen = macos.request_screen()
    for m in moves:
        if len(m) < 3: m += ['full', 'current'][len(m) - 1:]
        if m[2] == 'current': m[2] = screen
    flat = [i for i, m in enumerate(moves) if m[1] != 'fullscreen']
    native = [i for i, m in enumerate(moves) if m[1] == 'fullscreen']
    with ThreadPoolExecutor(len(flat) or 1) as pool:   # plain moves at once
        out = dict(zip(flat, pool.map(lambda i: place(*moves[i]), flat)))
    # native full screen is a Space animation, and macOS drops or misplaces one started during another: one window at a time,
    # each first out of any full screen and onto its display, so entering one never hides a window still to move
    if len(native) > 1:
        for i in native: out[i] = place(moves[i][0], 'full', *moves[i][2:])
    for i in native:
        if not place_failed(out.get(i, '')): out[i] = place(*moves[i])
    return '\n'.join(out[i] for i in range(len(moves)))


def model_note(output):   # an instant reply is read by the user, not the model
    return re.sub(r'\s*Look at the screen before saying[^.]*\.', '', output)


def place_failed(output):
    return any(line.startswith(('where must ', 'no window found', 'NOT DONE:')) for line in output.splitlines())


def keep_behind(mine, app, wait=1.5):
    """Give focus back to the user's app if `app` jumped forward by itself (a launch, Spotify starting to play);
    never undo a switch to some other app the user made."""
    if not mine or not app or macos.wants_focus() or prefs.pref('workIn', 'back') == 'front' or os.environ.get('RABIK_FOCUS_GUARD') == '1': return   # the native app watches late activations; don't hold every background open for 1.5 s
    names = {app.lower(), apps.proc_of(app).lower()}
    for _ in range(int(wait * 10)):   # some apps come forward late (Spotify, Chrome on a monitor)
        time.sleep(0.1)
        now = macos.osa('tell application "System Events" to get name of first process whose frontmost is true')
        if now != mine and now.lower() in names:
            macos.osa('on run argv\ntell application "System Events" to set frontmost of process (item 1 of argv) to true\nend run', mine); return


# Ways to say a screen or a size, in any order: "full screen chrome on my big screen", "move chrome to the external display and maximize it"
MOVE_WORDS = [(r'\bfull ?screen\b', 'fullscreen'), (r'\bmaximi[sz]ed?\b', 'full'),
              (r'\b(?:(?:big|bigger|large|larger|external|second) (?:screen|monitor|display)|external|monitor|display)\b', 'monitor'),
              (r'\b(?:laptop|macbook|built ?in|(?:small|smaller|little|mac) (?:screen|display))(?: (?:screen|display))?\b', 'laptop')]


def move_target(t):
    """"put chrome on the left of the monitor", "full screen chrome on my big screen" -> (app, left|right|full|center, laptop|monitor|current), or None.
    Everything but the app, one place and one screen must be filler, so "what's on my monitor" stays with the AI."""
    for pat, word in MOVE_WORDS:
        t = re.sub(pat, word, t)
    where, screen = re.findall(r'\b(left|right|full|fullscreen|center|middle)\b', t), re.findall(r'\b(laptop|monitor)\b', t)
    if len(where) > 1 or len(screen) > 1 or not (where or screen):
        return None
    who = re.sub(r'\b(?:snap|move|put|throw|send|make|left|right|full|fullscreen|center|middle|laptop|monitor|to|on|onto|the|my|of|and|side|half|screen)\b', ' ', t)
    who, where, screen = re.sub(r'\s+', ' ', who).strip(), where[0] if where else 'center', screen[0] if screen else 'current'
    if not who:
        return None
    if who in ('it', 'that', 'this', 'window', 'that window', 'this window'):
        app = Path(paths.LAST).read_text().strip() if os.path.exists(paths.LAST) and time.time() - os.path.getmtime(paths.LAST) < 600 else macos.front()[0]
    else:
        app = apps.app_named(who)
        if not app:
            return None
    return app, 'center' if where == 'middle' else where, screen
