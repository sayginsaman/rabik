"""Asking the user mid-ask: Allow cards and their answers (ask_user, relay), pickers, Rabik's own switches, setup an
ask needs (need), and the typed pop-up."""
import base64
import fcntl
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
import brain.paths   # choices: a local named paths hides the module there
from brain import apps, macos, paths, prefs, protocol, storage

__all__ = ['wait_commit', 'ask_user', 'pick', 'switches', 'picks', 'set_switch', 'thumb', 'choices', 'question_answer_path',
           'ask', 'NEEDS', 'need', 'allow_page_js', 'relay']


def wait_commit():
    """Early reasoning is allowed; tools and the final answer wait for the confirmed transcript."""
    path = os.environ.get('RABIK_COMMIT')
    if not path:
        return True
    parent = os.getppid()
    for _ in range(4500):   # 90 s: 60 s recording + finalization + an in-flight instant action
        if os.getppid() != parent:
            break
        if os.path.exists(path):
            return True
        time.sleep(0.02)   # a request started while the user talked goes on this soon after release
    return False


def ask_user(j, secs):
    """Hands a question to relay() (the box, or a dialog) and waits for the answer. None: no answer in time, or cancelled."""
    d, parent = os.environ['RABIK_ASK'], os.getppid()
    deadline = time.monotonic() + secs
    fd = os.open(os.path.join(d, 'permission.lock'), os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        # Parallel tool hooks must never overwrite each other's card or consume each other's answer.
        while True:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic() >= deadline or os.getppid() != parent: return None
                time.sleep(.05)
        if time.monotonic() >= deadline or os.getppid() != parent: return None
        answers = os.path.join(paths.DIR, 'answers'); os.makedirs(answers, mode=0o700, exist_ok=True)
        a = os.path.join(answers, uuid.uuid4().hex)
        storage.private_json(paths.question_path(d), {**j, '_a': a})
        while time.monotonic() < deadline:
            if os.path.exists(a) or os.getppid() != parent: break
            time.sleep(.02)   # the allowed action starts right after the click
        if not os.path.exists(a): return None
        with open(a) as f: answer = f.read().strip()
        os.remove(a)
        return answer


def pick(question, options):
    """{PICK}: the AI isn't sure which one the user means, so the user picks in the box. Prints the one picked."""
    if not options:
        return print('No options given.')
    s = ask_user({'pick': question, 'options': options[:8]}, 110) if os.environ.get('RABIK_ASK') else None   # 110 s: under the AI's 2-minute tool limit
    if s is None:
        return print('The user did not pick. Do not guess; say you need them to pick one.')
    if s.startswith('='):
        return print(f'None of these. The user typed their own answer instead: "{s[1:301]}". Go with that.')
    print(options[int(s)] if s.isdigit() and int(s) < len(options) else 'None of these, the user said. Do not guess; say so in one line.')


def switches():
    """{key: label} for every on/off switch in Settings, read from the Settings page itself. Pause stays manual; Safe mode only turns on (set_switch)."""
    with open(os.path.join(os.path.dirname(paths.ME), 'ui', 'settings.html')) as f:
        page = f.read()
    return {k: html.unescape(b) for b, k in re.findall(r'<b[^>]*>([^<]+)</b>(?:<span[^>]*>.*?</span>)?</div><label class="sw"><input type="checkbox" data-k="(\w+)"', page)
            if k != 'paused'}


def picks():
    """{key: (label, {option label: value})} for each choice setting, read from the page."""
    with open(os.path.join(os.path.dirname(paths.ME), 'ui', 'settings.html')) as f:
        page = f.read()
    return {k: (html.unescape(b), {html.unescape(l): v for v, l in re.findall(r'<button data-v="([^"]+)">([^<]+)</button>', btns)})
            for b, k, btns in re.findall(r'<b[^>]*>([^<]+)</b>(?:<span[^>]*>.*?</span>)?</div><div class="seg" data-k="(\w+)">((?:<button[^>]*>[^<]*</button>)+)', page)}


def set_switch(words, on):
    """{SET}: the setting whose name shares the most words with what the user said (first 3 letters, so "asking" finds "Ask").
    on: on|off for a switch, or one of a choice setting's options."""
    stem = lambda t: {w[:3] for w in re.findall(r'[a-z]+', t.lower()) if w not in ('the', 'me', 'my', 'on', 'off', 'setting', 'in', 'a')}
    if on not in ('on', 'off'):
        rows = picks()
        k = max(rows, key=lambda k: len(stem(words) & stem(rows[k][0])) * 2 + len(stem(on) & stem(' '.join(rows[k][1]))))
        name, options = rows[k]
        o = max(options, key=lambda o: len(stem(on) & stem(o + ' ' + options[o])))
        if not stem(words) & stem(name) or not stem(on) & stem(o + ' ' + options[o]):
            return print('No such setting. Choices: ' + '; '.join(f'{n}: {", ".join(o)}' for n, o in rows.values()) + '. Switches (on|off): ' + ', '.join(switches().values()))
        if k == 'client':
            return print('Only the user can change the AI client in Settings.')
        if os.environ.get('RABIK_ASK'):
            ask_user({'set': k, 'value': options[o]}, 5)
        else:
            prefs.save_pref(k, options[o])
        return print(f'{name} is now {o}.')
    rows = switches()
    k = max(rows, key=lambda k: len(stem(words) & stem(rows[k])))
    if not stem(words) & stem(rows[k]):
        return print('No such switch. Switches: ' + ', '.join(rows.values()) + '. Choices: ' + '; '.join(f'{n}: {", ".join(o)}' for n, o in picks().values()))
    if k == 'safe' and on == 'off':   # the AI may make Rabik safer, never less safe: a web page could ask it to
        return print('Only the user can turn Safe mode off: Settings > Account & Access > Safety. It is still on.')
    if os.environ.get('RABIK_ASK'):
        ask_user({'set': k, 'value': on == 'on'}, 5)
    else:
        prefs.save_pref(k, on == 'on')
    print(f"{rows[k]} is now {on}.")


def thumb(path):
    """A Quick Look thumbnail (images, PDFs, documents, videos) as a data URL, or '' if macOS has none."""
    out = tempfile.mkdtemp()   # one folder each: files with the same name must not share a thumbnail
    try:
        subprocess.run(['qlmanage', '-t', '-s', '480', '-o', out, path], capture_output=True, timeout=4)
        png = os.path.join(out, os.path.basename(path) + '.png')
        return 'data:image/png;base64,' + base64.b64encode(Path(png).read_bytes()).decode() if os.path.exists(png) else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''
    finally:
        shutil.rmtree(out, True)


def choices(options):
    """What the box shows per option: a file gets its name, its folder and date, and a preview; anything else is just its text."""
    from concurrent.futures import ThreadPoolExecutor
    paths = [os.path.expanduser(o) for o in options]
    imgs = list(ThreadPoolExecutor(len(paths)).map(lambda p: thumb(p) if os.path.isfile(p) else '', paths))   # Quick Look hangs on folders
    return [{'label': os.path.basename(p.rstrip('/')) or p, 'sub': os.path.basename(os.path.dirname(p.rstrip('/'))) + time.strftime(' · %b %-d, %Y', time.localtime(os.path.getmtime(p))),
             'path': os.path.dirname(p.rstrip('/')).replace(brain.paths.HOME, '~', 1), 'img': img,
             'kind': 'Folder' if os.path.isdir(p) else os.path.splitext(p)[1][1:6].upper()}
            if os.path.exists(p) else {'label': o, 'sub': '', 'path': '', 'img': '', 'kind': ''} for o, p, img in zip(options, paths, imgs)]


def allow_page_js(app, ask=False):
    """Chromium browsers: View > Developer > Allow JavaScript from Apple Events, clicked by its menu. Asks the user once (Settings: pageJS), then keeps it on."""
    if ask and not prefs.pref('pageJS', False) and not prefs.pref('fixSetup', False):
        if not os.environ.get('RABIK_ASK') or ask_user({'need': 'page-js', 'app': app, 'q': f'I can turn on page reading in {app} for you',
                                                          'cmd': 'View > Developer > Allow JavaScript from Apple Events, kept on.'}, 60) != 'y':
            return False
        if not os.environ.get('RABIK_AGENT'): ask_user({'set': 'pageJS', 'value': True}, 5)   # an agent's chip sets it on Allow
    # shortcut: English menu names only; a translated Chrome needs the item found by position
    return macos.osa('on run argv\ntell application "System Events" to tell process (item 1 of argv)\n'
               'set m to menu item "Allow JavaScript from Apple Events" of menu 1 of menu item "Developer" of menu 1 of menu bar item "View" of menu bar 1\n'
               'if value of attribute "AXMenuItemMarkChar" of m is missing value then click m\nreturn "on"\nend tell\nend run', apps.proc_of(app)) == 'on'


# Setup an agent can ask for mid-task. macOS lets only the user flip its privacy switches; page reading Rabik turns on itself.
NEEDS = {'accessibility': 'Accessibility', 'screen': 'Screen Recording', 'automation': 'Automation', 'calendar': 'Calendar',
         'microphone': 'Microphone', 'page-js': 'page reading'}


def need(kind, why='', app='', do=False):
    """Missing setup that would help this task: ask on its card, then wait for the grant."""
    if kind not in NEEDS: return 'Use one of: ' + ', '.join(NEEDS) + '.'
    name = NEEDS[kind] + (f' for {app}' if app else '')
    skip = f'Not now: continue without {name} by the next-best route, and say in the result what you skipped.'
    if not os.environ.get('RABIK_ASK'): return f'{name} is off. Tell the user it would help, in one line.'
    wait = 900 if os.environ.get('RABIK_AGENT') else 110   # main asks: under the AI's 2-minute tool limit, as pick()
    if kind == 'page-js':
        app = app or 'Google Chrome'
        if do or prefs.pref('fixSetup', False): protocol.emit([f'▸ Turning on page reading in {app}'])
        elif ask_user({'need': kind, 'app': app, 'q': f'I can turn on page reading in {app} for you', 'cmd': why}, min(wait, 600)) != 'y': return skip
        return f'Turned on {name}. Continue, and say so in one line.' if allow_page_js(app) else f'Could not turn on {name}. ' + skip
    return f'{name} is on now. Continue the task with it.' if ask_user({'need': kind, 'app': app, 'q': f'Turn on {name}', 'cmd': why}, wait) == 'y' else skip


def question_answer_path(directory, question):
    path = str(question.get('_a', ''))
    return path if os.path.dirname(path) == os.path.join(paths.DIR, 'answers') and re.fullmatch(r'[a-f0-9]{32}', os.path.basename(path)) else os.path.join(directory, 'a')


def relay(p=None, directory=None):
    """Passes the gate's question to the box ("? <question>\t<command>\t<answer file>"), or a dialog when there is no box."""
    directory = directory or (p.ask if p is not None else os.environ['RABIK_ASK'])
    q, pointer = paths.question_path(directory), os.path.join(directory, 'point')
    while (p is None and os.path.isdir(directory)) or (p is not None and p.poll() is None) or os.path.exists(pointer) or (os.path.isdir(directory) and any(n.startswith('hands-') for n in os.listdir(directory))):
        for name in sorted(n for n in os.listdir(directory) if n.startswith('hands-')) if os.path.isdir(directory) else []:
            path = os.path.join(directory, name)
            with open(path) as f:   # step, target, pointer and drawing events only: a sandboxed command can write here too
                for line in f.read().splitlines():
                    if line[:2] in ('▸ ', '▣ ', '@ ', '✎ '): protocol.say(line[0], line[2:])
            os.remove(path)
        if os.path.exists(pointer):
            with open(pointer) as f:
                protocol.say('@', f.read())
            os.remove(pointer)
        if os.path.exists(q):
            waiting = getattr(p, 'waiting', None) if p is not None else None
            if waiting is not None: waiting.set()
            progress = getattr(p, 'progress', None) if p is not None else None
            if callable(progress): progress()
            with open(q) as f: j = json.load(f)
            os.remove(q)
            a = question_answer_path(directory, j)
            if 'set' in j:   # "⚙ <key> <true|false>": the app flips it, so the Settings window and the app agree
                k, v, rows = j['set'], j.get('value'), picks()
                if not (k in switches() and isinstance(v, bool) and (k != 'safe' or v) or k in rows and k != 'client' and v in rows[k][1].values()):
                    pass   # only what --set can ask for: never a server address, key, the AI client, or Safe mode off
                elif os.environ.get('RABIK_UI') == '1':
                    print(f"⚙ {j['set']} {j['value'] if isinstance(j['value'], str) else 'true' if j['value'] else 'false'}", flush=True)
                else:   # no app running: it reads the file when it starts
                    prefs.save_pref(j['set'], j['value'])
                Path(a + '.tmp').write_text('ok')
                os.rename(a + '.tmp', a)
            elif 'agentShow' in j:   # "▤ <task ID>": the app shows that task's work once this ask ends
                if os.environ.get('RABIK_UI') == '1' and re.fullmatch(r'[a-f0-9]{32}', str(j['agentShow'])): print('▤ ' + j['agentShow'], flush=True)
                Path(a + '.tmp').write_text('ok')
                os.rename(a + '.tmp', a)
            elif 'pick' in j and os.environ.get('RABIK_UI') == '1':   # "◇ {json}": the choices card
                print('◇ ' + json.dumps({'q': j['pick'], 'options': choices(j['options']), 'a': a}), flush=True)
            elif 'pick' in j:
                r = macos.osa('on run argv\nset r to choose from list (rest of argv) with prompt (item 1 of argv)\nif r is false then return ""\nreturn item 1 of r\nend run', j['pick'], *j['options'])
                Path(a + '.tmp').write_text(str(j['options'].index(r)) if r in j['options'] else '')
                os.rename(a + '.tmp', a)   # whole, or the waiting side reads it half-written
            elif os.environ.get('RABIK_UI') == '1':
                print(f"? {j['q']}\t{' '.join(j['cmd'].split())}\t{a}" + (f"\t\t\t{json.dumps({'need': j['need'], 'app': j.get('app', '')})}" if j.get('need') else
                      f"\t\tretry\t{' '.join(j.get('details', '').split())}" if j.get('retry') else ''), flush=True)   # not say(): it would squash the tabs
            else:
                buttons = ['Not now', 'Retry'] if j.get('retry') else ["Don't Allow", 'Allow']
                result = macos.osa('on run argv\ndisplay dialog (item 2 of argv) with title (item 1 of argv) buttons (items 3 thru -1 of argv)\n'
                             'return button returned of result\nend run', j['q'], j['cmd'], *buttons)
                Path(a + '.tmp').write_text('r' if result == 'Retry' else 'y' if result == 'Allow' else 'n')
                os.rename(a + '.tmp', a)
        time.sleep(0.02)   # the final answer waits for this loop to notice the worker ended; cards and steps show sooner too


def ask():
    out = macos.osa('tell application "System Events"\nactivate\nset r to display dialog "What should I do?" default answer "" '
              'buttons {"Cancel", "Go"} default button "Go" with title "Rabik"\nreturn text returned of r\nend tell')
    return out.strip()
