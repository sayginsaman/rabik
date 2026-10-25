"""Hands: native accessibility actions through Rabik.app (--hands), the window map they act on, menu bar items, and
which actions may replay."""
import json
import os
import re
import select
import shlex
import subprocess
import sys
import time
from brain import environ, interaction, macos, paths, policy, prefs, protocol, turn, wording

__all__ = ['HANDS_VERBS', 'HANDS_RISK', 'agent_window', 'handed_page', 'agent_window_id', 'hands_pin', 'hands_env', 'GONE',
           'hands_call', 'hands_action', 'hands_map', 'hands', 'menu_bar_icons', 'with_icons', 'menu_bar_click', 'hands_valid',
           'hands_replayable', 'hands_command', 'fast_hands']


def agent_window(app):
    """The browser window this agent task opened, while it is in the same browser; 0 when there is none."""
    try:
        with open(os.path.join(paths.agent_gate_dir(environ.ask_dir(required=True)), 'browser-window.json')) as f: saved = json.load(f)
        return saved['window'] if saved.get('app') == app and type(saved.get('window')) is int else 0
    except (KeyError, OSError, ValueError, AttributeError): return 0


def handed_page():
    """The user's page this agent task was handed (outside its sandbox): the one page of the user's it may act on."""
    try:
        with open(os.path.join(paths.agent_gate_dir(environ.ask_dir(required=True)), 'work-page.json')) as f: page = json.load(f)
        return page if isinstance(page, dict) else {}
    except (KeyError, OSError, ValueError): return {}


# Native actions resolve first, so an ID or picture coordinate cannot hide a consequential label.
HANDS_VERBS = {'see', 'click', 'menu', 'scroll', 'scroll-to', 'press', 'drag', 'type', 'type-after', 'wait'}


HANDS_RISK = (r'\b(buy|purchase|pay|payment|order|bid|checkout|delete|remove|erase|send|submit|transfer|withdraw|donate|'
              r'subscribe|authorize|grant access|allow access|confirm|log.?out|sign.?out|unsubscribe|book|reserve|publish|post|'
              r'merge|deploy|trash|discard|wipe|format|apply(?! filters| changes| settings| coupon| code| promo| discount| theme| style| formatting))\b')


def agent_window_id(app):
    """The Core Graphics id of the browser window this agent task opened in app, else of the user's window it was handed ('' when
    neither); None when that window is gone."""
    if not app or not environ.agent(): return ''
    handed = handed_page()
    window = agent_window(app) or (handed.get('window') if str(handed.get('app', '')).casefold() == app.casefold() and type(handed.get('window')) is int else 0)
    if not window: return ''
    quoted = app.replace('\\', '\\\\').replace('"', '\\"')
    try:
        r = subprocess.run(['osascript', '-e', f'tell application "{quoted}" to get bounds of window id {window}'], capture_output=True, text=True, timeout=2)
        left, top, right, bottom = map(float, r.stdout.strip().split(', '))
        r = subprocess.run([paths.APP, '--window-target', app, '', json.dumps([left, top, right - left, bottom - top])], capture_output=True, text=True, timeout=2)
        identifier = str(json.loads(r.stdout)['windowID'])
        return identifier if identifier.isdigit() and int(identifier) > 0 else None
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired): return None


def hands_pin(args, target=None, state=None):
    """(window id, strict): the window a hands call must stay in. Agents keep their own browser window, else the window they mapped
    last in that app; a main ask follows the front one, never into the user's other windows (native, hands.json.windows). Only a pin from the last map may give way to a fresh look."""
    if isinstance(target, dict): return str(target.get('windowID', '')), True
    if state is not None or not environ.agent(): return '', False
    mapped = macos.cached_hands() or {}
    looks = args[:1] in (['see'], ['identify'], ['read'])
    app = (args[1] if len(args) > 1 else environ.front_app('')) if looks else str(mapped.get('app', ''))
    own = agent_window_id(app)
    if own != '': return own, True
    same = not looks or app.casefold() in (str(mapped.get('app', '')).casefold(), str(mapped.get('pid', '')))
    return (str(mapped.get('windowID', '')) if same else ''), False


def hands_env(args, target=None, state=None):
    """The helper's environment with its window pin, or an error when this task's own window is gone (never another window)."""
    window, strict = hands_pin(args, target, state)
    if window is None: return None, False
    env = {**os.environ, 'RABIK_DIR': paths.DIR, 'RABIK_FOCUS_REQUESTED': '1' if macos.wants_focus() else '0'}
    if window.isdigit() and int(window) > 0: env['RABIK_HANDS_WINDOW'] = window
    else: env.pop('RABIK_HANDS_WINDOW', None)
    return env, bool(window) and not strict


GONE = f"This task's own browser window closed. Nothing was done. Open the page again with {paths.WEB} read <url>."


def hands_call(args, receipt=None, timeout=30, state=None, head=False, target=None):
    if turn.STOPPING: raise InterruptedError('Request cancelled')
    env, loose = hands_env(args, target, state)
    if env is None: return subprocess.CompletedProcess([paths.APP, '--hands', *args], 1, GONE, '')
    env.update({**({'RABIK_HANDS_STATE': state} if state else {}), **({'RABIK_HANDS_HEAD': '1'} if head else {}),
                'RABIK_HANDS_RECEIPT': '1' if receipt is not None else '0'})
    if loose and args[:1] in (['see'], ['identify'], ['read']):   # the window it mapped last closed: a fresh look may map another
        r = hands_call(args, receipt, timeout, state, head, target={**(macos.cached_hands() or {})})
        return hands_call(args, receipt, timeout, state, head, target={}) if r.returncode and 'window closed or changed' in r.stdout else r
    process = subprocess.Popen([paths.APP, '--hands', *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=env)
    try:
        out, err = process.communicate(json.dumps(receipt) if receipt is not None else None, timeout=timeout)
        return subprocess.CompletedProcess(process.args, process.returncode, out, err)
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.communicate(timeout=.2)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()


def hands_action(args, authorize, timeout=30):
    """Resolve, authorize, and act in one native process so its first AX map is reused."""
    if turn.STOPPING: raise InterruptedError('Request cancelled')
    env, _ = hands_env(args)
    if env is None: return None, subprocess.CompletedProcess([paths.APP, '--hands', *args], 1, GONE, '')
    env.update(RABIK_HANDS_SESSION='1', RABIK_HANDS_RECEIPT='0')
    process = subprocess.Popen([paths.APP, '--hands', *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=env)
    try:
        if not select.select([process.stdout], [], [], timeout)[0]:
            raise subprocess.TimeoutExpired(process.args, timeout)
        first = process.stdout.readline()
        try:
            check = json.loads(first)
        except ValueError:
            out, err = process.communicate(timeout=timeout)
            return None, subprocess.CompletedProcess(process.args, process.returncode, first + out, err)
        allowed = authorize(check)
        out, err = process.communicate('y\n' if allowed else 'n\n', timeout=timeout)
        return check, subprocess.CompletedProcess(process.args, process.returncode, out, err)
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.communicate(timeout=.2)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()


def hands_map(app='', target=None):
    """A bounded native map; failed accessibility never falls back to guessing a target."""
    try:
        r = hands_call(['see', app] if app else ['see'], timeout=2, target=target)
        if r.returncode:
            return None
        with open(paths.hands_state()) as f:
            m = json.load(f)
        return {**m, 'description': r.stdout.strip()}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def hands(*args):
    """The only model-facing native helper. No approval/force/app-changing flags are accepted."""
    if not args or args[0] not in HANDS_VERBS or any(a.startswith('--') for a in args[1:]):
        return 'Use --hands see|menu|click|scroll|scroll-to|press|drag|type|type-after|wait; no flags.', False
    if not interaction.wait_commit():
        return 'The request was cancelled before the transcript was confirmed.', False
    try:
        if args[0] == 'see':
            r = hands_call(list(args), timeout=2)
            if r.returncode and 'Accessibility' in r.stdout: return interaction.need('accessibility', 'To read apps for this task.'), False
            return with_icons(r.stdout.strip()), not r.returncode
        if args[0] == 'menu':
            r = hands_call(list(args), timeout=2)
            if r.returncode and 'Accessibility' in r.stdout: return interaction.need('accessibility', 'To use app menus for this task.'), False
            protocol.emit([line for line in r.stdout.splitlines() if line.startswith('▣ ')])
            return '\n'.join(line for line in r.stdout.strip().splitlines() if not line.startswith('▣ ')), not r.returncode
        if not os.path.exists(paths.hands_state()) and not hands_map(environ.front_app('')):
            r = hands_call(['see'] + ([environ.front_app(required=True)] if environ.front_app() else []), timeout=6)   # a slow app, not a missing permission: say which
            if 'Accessibility' in r.stdout: return interaction.need('accessibility', 'To click and type in apps for this task.'), False
            if r.returncode or 'Accessibility' in r.stdout:
                return r.stdout.strip() or 'Could not read the front app. Run see "<app>" for the app you mean.', False
        denied = []
        def authorize(check):
            if check.get('args') != list(args) or not isinstance(check.get('labels'), list) or not isinstance(check.get('pid'), int):
                denied.append('Could not resolve the hands action safely.')
                return False
            labels = check['labels']
            if check.get('secure') and args[0] == 'type':
                request = environ.request('')
                ask = environ.ask_dir()
                if ask and os.path.exists(paths.request_file(ask)):
                    with open(paths.request_file(ask)) as f:
                        request = f.read()
                if not (re.search(r'\b(type|enter|fill|paste)\b', request, re.I) and re.search(r'\b(password|passcode|pin|secret|secure|verification|one.time|otp|card|cvv|ssn|token|account|routing)\b', request, re.I)) or re.search(r"\b(don.t|do not|never)\s+(type|enter|fill|paste)\b", request, re.I):
                    denied.append('Secure field: the user must explicitly request typing into it.')
                    return False
            if check.get('risky') and prefs.pref('safe', True) and not policy.task_allowed('hands ' + args[0]):
                what = ' → '.join(labels) or args[0]
                if not environ.ask_dir():
                    denied.append(f'Safe mode: {args[0]} "{what}" needs the user’s Allow card.')
                    return False
                question = f'{args[0].capitalize()} "{what[:120]}"?'
                answer = interaction.ask_user({'q': question, 'cmd': f'{check["pid"]}: {args[0]} "{what[:300]}"', 'task': policy.managed_agent()}, 60)
                if answer == 'task' and policy.managed_agent(): policy.allow_for_task('hands ' + args[0])
                elif answer != 'y':
                    denied.append('The user said no. Do not try another way; say it was not done.')
                    return False
            return True
        check, r = hands_action(list(args), authorize)
        if denied:
            return denied[0], False
        if check is None and args[0] == 'click' and 'No visible control named' in r.stdout and not environ.in_menu_bar_click():
            bar = menu_bar_click(args[1])
            if bar:
                return bar
        if check is None or r.returncode:
            return interaction.need('accessibility', 'To click and type in apps for this task.') if 'Accessibility' in r.stdout else r.stdout.strip(), False
        if not r.returncode and check.get('windowID'):
            target = {k: check[k] for k in ('pid', 'windowID', 'windowFrame', 'window', 'app')}
            target['action'] = args[0]
            target['direction'] = args[1] if args[0] == 'scroll' else ''
            protocol.emit(['▣ ' + json.dumps(target)] + [line for line in r.stdout.splitlines() if line.startswith('@ ')])
        return '\n'.join(line for line in r.stdout.strip().splitlines() if not line.startswith('@ ')), not r.returncode
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
        return f'Hands could not finish: {e}', False


def menu_bar_icons():
    """Every top-right menu bar icon by name (Wi-Fi, Bluetooth, battery, clock, app icons), read without touching the target map."""
    try:
        r = hands_call(['see', 'MenuBarAgent'], timeout=2, state=paths.hands_state() + '.bar')   # macOS 26 keeps them all here
    except (OSError, subprocess.TimeoutExpired):
        return []
    icons = re.findall(r'^\[\d+\] MenuBarItem "(.+?)"(?: = "(.*?)")? \(at ([1-9]\d*),', r.stdout, re.M) if not r.returncode else []   # x 0: its own app menus
    return [(n, v) for n, v, _ in icons]


def with_icons(description):
    icons = menu_bar_icons()
    return description + ('\nMenu bar icons, top right (click any by name from any app): ' + '; '.join(f'{n} ({v})' if v else n for n, v in icons) if icons else '')


def menu_bar_click(target):
    """Anything on the Mac is fair game: a click that misses the front app tries the top-right menu bar icons, then reads the panel."""
    want = wording.dashes(target).lower()
    hits = [n for n, _ in menu_bar_icons() if want in wording.dashes(n).lower()]
    if len(hits) != 1 or not hands_map('MenuBarAgent'):   # only now does the menu bar become the target
        return None
    with environ.clicking_menu_bar():
        result, ok = hands('click', hits[0])
    if ok:
        time.sleep(0.3)   # the panel opens in Control Center; its map becomes the next target
        panel = hands_call(['see', 'Control Center'], timeout=2)
        if not panel.returncode:
            result += '\nPanel:\n' + panel.stdout.strip()
    return result, ok


def hands_valid(args):
    verb, rest = args[0], args[1:]
    if verb == 'menu': return len(rest) == 2 and bool(rest[0]) and len(rest[1].split('>')) > 1 and all(p.strip() for p in rest[1].split('>'))
    if verb == 'click':
        if not rest: return False
        i, seen = 1, set()
        while i < len(rest):
            option = rest[i]
            if option not in ('near', 'double', 'right', 'front') or option in seen: return False
            seen.add(option)
            i += 2 if option == 'near' else 1
        return i == len(rest)
    if verb == 'type': return 2 <= len(rest) <= 4 and all(a in ('submit', 'append') for a in rest[2:])
    if verb == 'type-after': return len(rest) == 2 and bool(rest[0])
    if verb == 'drag': return len(rest) == 2
    if verb == 'scroll-to': return len(rest) == 1
    if verb == 'scroll': return 1 <= len(rest) <= 3 and rest[0] in ('down', 'up', 'left', 'right')
    if verb == 'press': return 1 <= len(rest) <= 2
    if verb == 'wait': return len(rest) <= 1
    return False


def hands_replayable(command):
    """Persist labels/menu paths, never transient map IDs or image coordinates."""
    if '--hands' not in command: return True
    try:
        parts = shlex.shlex(command, posix=True, punctuation_chars=';&|')
        parts.whitespace_split = True
        groups, group = [], []
        for token in parts:
            if token in (';', '&&'):
                if group: groups.append(group)
                group = []
            elif token in ('|', '||', '&'):
                return False
            else:
                group.append(token)
        if group: groups.append(group)
        for group in groups:
            if '--hands' not in group:
                if not group or not (group[0] in ('open', 'osascript', 'test', '[') or group[0] == paths.ME and len(group) > 1 and group[1] in ('--show', '--place', '--play', '--queue', '--type')): return False
                continue
            i = group.index('--hands')
            if group[:i] not in ([paths.ME], [sys.executable, paths.ME], ['python3', paths.ME]):
                return False
            args = group[i+1:]
            if not args or args[0] not in HANDS_VERBS - {'see'} or any(a.startswith('--') for a in args) or not hands_valid(args):
                return False
            targets = args[1:3] if args[0] == 'drag' else args[1:2] if args[0] in ('click', 'type', 'type-after') else args[3:4] if len(args) == 4 and args[0] == 'scroll' else args[2:3] if len(args) == 3 and args[0] == 'scroll' and args[2] != 'all' and not args[2].isdigit() else []
            if any(re.fullmatch(r'\d+|(?:\d+:)?-?[\d.]+,-?[\d.]+', t) for t in targets):
                return False
        return True
    except ValueError:
        return False


def hands_command(text):
    args = None
    m = re.fullmatch(r'scroll (down|up)(?: (a bit|to the top|to the bottom))?', text)
    if m:
        if m[2] and m[2].startswith('to the '):
            args = ['scroll', 'up' if m[2] == 'to the top' else 'down', 'all']
        else:
            args = ['scroll', m[1], '0.25'] if m[2] == 'a bit' else ['scroll', m[1]]
    elif text in ('scroll to the top', 'scroll to the bottom'):
        args = ['scroll', 'up' if text.endswith('top') else 'down', 'all']
    elif text in ('page down', 'page up'):
        args = ['scroll', text.split()[1]]
    elif text == 'go back':
        args = ['press', 'cmd+[']
    elif text in ('hit enter', 'hit return', 'escape', 'hit escape'):
        args = ['press', 'esc' if 'escape' in text else 'return']
    else:
        m = re.fullmatch(r'press (return|enter|esc|escape|tab|space|pagedown|pageup|home|end|left|right|up|down|(?:(?:cmd|command|ctrl|control|shift|alt|option)\+)+(?:[a-z0-9\[\]]|return|delete|esc))', text)
        if m:
            args = ['press', m[1]]
    click = re.fullmatch(r'(?:click|tap) (.+)|press the (.+) button', text)
    if not args and not click:
        return None
    return args, (click[1] or click[2]) if click and not args else None


def fast_hands(text):
    text = re.sub(r'\bteh\b', 'the', text)
    icon = re.fullmatch(r'(?:open|show|click|tap)(?: on)? (?:the |my )?(.+?)(?: (?:menu|icon|panel)| (?:menu|icon|panel)? ?(?:in|on|from) (?:my |the )?menu ?bar)', text)   # any icon; "click bluetooth" alone stays in the app
    command = hands_command(text)
    if not command and not icon: return None
    # Native actions wait for final words; existing safe built-ins can still run live.
    if environ.live():
        return None
    if icon:   # a top-right menu bar icon by any name: no AI
        bar = menu_bar_click(icon[1].replace('wifi', 'wi-fi'))
        if bar and bar[1]:
            return bar[0].splitlines()[0]
        if not command: return None
    args, target = command
    m = (macos.cached_hands() if environ.hands_file() else None) or hands_map(environ.front_app(''))
    if not m:
        return None
    if target:
        hits = [n for n in m.get('nodes', []) if wording.plain(n['label']) == target]
        if len(hits) != 1 or re.search(HANDS_RISK, hits[0]['label'], re.I):
            return None
        args = ['click', hits[0]['label']]
    result, ok = hands(*args)
    return result.splitlines()[0] if ok or 'The user said no.' in result else None
