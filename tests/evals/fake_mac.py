"""Fake Mac tool outputs for eval runs. Installed by the test harness and sitecustomize. Stdlib only."""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()

def _load():
    path = os.environ.get('ATTICUS_EVAL_STATE', '')
    if not path or not os.path.isfile(path):
        return {'pages': {}, 'hands': {}, 'log': [], 'effects': []}
    with _LOCK:
        with open(path) as f:
            return json.load(f)


def _save(state):
    path = os.environ.get('ATTICUS_EVAL_STATE', '')
    if not path:
        return
    with _LOCK:
        with open(path + '.tmp', 'w') as f:
            json.dump(state, f)
        os.replace(path + '.tmp', path)


def _log(kind, detail):
    state = _load()
    row = {'t': time.time(), 'kind': kind, 'detail': detail}
    state.setdefault('log', []).append(row)
    _save(state)
    path = os.environ.get('ATTICUS_EVAL_LOG', '')
    if path:
        with open(path, 'a') as f:
            f.write(json.dumps(row) + '\n')


def _page(state):
    key = state.get('page', 'default')
    return state.setdefault('pages', {}).setdefault(key, {'title': '', 'body': '', 'controls': []})


def _web_js_payload(argv_tail):
    m = re.search(r'\)\s*\(\s*"(\w+)"\s*,\s*"((?:\\.|[^"\\])*)"\s*,\s*"((?:\\.|[^"\\])*)"\s*\)\s*$', argv_tail)
    if not m:
        return None
    cmd, n, text = m.group(1), m.group(2), m.group(3)
    if cmd not in ('read', 'click', 'fill', 'ready', 'name'):
        return None
    return cmd, n, text


def _web_reply(cmd, n, text, state):
    page = _page(state)
    url = state.get('url', 'https://fixture.invalid')
    controls = page.get('controls', [])
    if cmd == 'ready':
        body = page.get('body', '')
        h = sum(ord(c) for c in body[:3000])
        return json.dumps({'ready': True, 'signature': f'{url}|{h}'})
    if cmd == 'read':
        lines = [url, page.get('title', ''), '', page.get('body', ''), '', 'Controls:']
        for i, c in enumerate(controls, 1):
            kind = c.get('kind', 'button')
            label = c.get('label', '')
            extra = f' = "{c["value"]}"' if c.get('value') else ''
            lines.append(f'{i} {kind}: {label}{extra}')
        _log('web_read', {'page': state.get('page', 'default')})
        return '\n'.join(lines)
    if cmd == 'name':
        try:
            i = int(n) - 1
            c = controls[i]
        except (ValueError, IndexError):
            return json.dumps({'what': '', 'short': '', 'url': url})
        what = c.get('what', c.get('label', ''))
        return json.dumps({'what': what, 'short': c.get('label', ''), 'url': url})
    if cmd == 'click':
        try:
            i = int(n) - 1
            c = controls[i]
        except (ValueError, IndexError):
            return f'No control {n}. Read the page again.'
        _log('web_click', {'n': n, 'label': c.get('label', '')})
        if c.get('goto_page'):
            state['page'] = c['goto_page']
            _save(state)
        if c.get('effect'):
            state.setdefault('effects', []).append(c['effect'])
            _save(state)
        return f'Clicked {n}: {c.get("label", "")}'
    if cmd == 'fill':
        try:
            i = int(n) - 1
            c = controls[i]
        except (ValueError, IndexError):
            return f'No control {n}. Read the page again.'
        c['value'] = text
        _log('web_fill', {'n': n, 'label': c.get('label', ''), 'text': text[:80]})
        if c.get('effect'):
            state.setdefault('effects', []).append(c['effect'])
            _save(state)
        return f'Filled {n}: {c.get("label", "")} = "{text[:60]}"'
    return 'Use read, click or fill.'


READ_CHUNK = 8000


def _document_text(state):
    if state.get('document'):
        return state['document']
    return state.get('hands', {}).get('description', '')


def _ocr_text(state):
    if state.get('ocr') is not None:
        return state['ocr']
    doc = _document_text(state)
    if len(doc.strip()) >= 160:
        return doc
    return 'Visible question from unfamiliar app. ' * 20


def _hands_read(args, state):
    full = _document_text(state)
    more = len(args) > 1 and args[-1] == 'more'
    start = state.get('read_offset', 0) if more else 0
    if not more:
        state['read_offset'] = 0
    chunk = full[start:start + READ_CHUNK]
    state['read_offset'] = start + len(chunk)
    incomplete = state['read_offset'] < len(full)
    _save(state)
    _log('hands_read', {'more': more, 'chars': len(chunk), 'incomplete': incomplete})
    return json.dumps({'text': chunk, 'incomplete': incomplete, 'web': bool(state.get('pages'))})  # real AX reports a web area for browser windows


def _hands_label(args, state):
    hands = state.get('hands', {})
    nodes = {n['id']: n for n in hands.get('nodes', [])}
    verb = args[0]
    if verb == 'see':
        return hands.get('description', 'Fixture window map')
    if verb == 'menu' and len(args) == 3:
        return f'Clicked {args[2]}'
    target = args[1] if len(args) > 1 else ''
    label = nodes.get(int(target), {}).get('label', target) if target.isdigit() else target
    risky = any(re.search(p, label, re.I) for p in (r'buy|purchase|checkout|send|delete',))
    check = {'args': list(args), 'labels': [label], 'risky': risky, 'secure': False,
             'pid': state.get('pid', 4242), 'signature': 'eval', 'windowID': '99',
             'windowFrame': [0, 0, 800, 600], 'window': state.get('front_window', 'Fixture'),
             'app': state.get('front_app', 'Fixture')}
    return json.dumps(check)


def _hands_act(args, state):
    hands = state.get('hands', {})
    nodes = {n['id']: n for n in hands.get('nodes', [])}
    verb, target = args[0], args[1] if len(args) > 1 else ''
    if verb == 'see':
        path = os.environ.get('ATTICUS_HANDS_STATE', '')
        if path:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with open(path, 'w') as f:
                json.dump(hands, f)
        _log('hands_see', {'app': state.get('front_app')})
        return hands.get('description', '1 button: Save\n2 box: Notes')
    label = nodes.get(int(target), {}).get('label', target) if target.isdigit() else target
    _log(f'hands_{verb}', {'target': target, 'label': label})
    for n in nodes.values():
        if str(n.get('id')) == str(target) or n.get('label') == label:
            if n.get('effect'):
                state.setdefault('effects', []).append(n['effect'])
                _save(state)
            break
    if verb == 'type' and len(args) > 2:
        return f'Typed into "{label}"'
    if verb == 'menu':
        return f'Opened menu {args[2]}'
    return f'Clicked "{label}"'


class _FakeProc:
    def __init__(self, args, stdout='', returncode=0, stdin_pipe=False):
        self.args = args
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = ''
        self.stdin = subprocess.PIPE if stdin_pipe else None
        self._buf = stdout

    def communicate(self, input=None, timeout=None):
        return self._buf, self._stderr

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return 0 if self.returncode is not None else None

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class _SessionProc(_FakeProc):
    def __init__(self, args, receipt, finish):
        super().__init__(args, returncode=None, stdin_pipe=True)
        self.stdout = tempfile.TemporaryFile(mode='w+')
        self._finish = finish
        self.stdout.write(receipt.rstrip('\n') + '\n')
        self.stdout.seek(0)

    def communicate(self, input=None, timeout=None):
        try:
            if (input or '').strip() == 'y':
                self._buf, self.returncode = self._finish()
            else:
                self._buf, self.returncode = 'Action cancelled.', 1
            return self._buf, self._stderr
        finally:
            self.stdout.close()

    def terminate(self):
        self.stdout.close()
        super().terminate()

    def kill(self):
        self.stdout.close()
        super().kill()


def run(args, **kwargs):
    state = _load()
    cmd = list(args)
    if not cmd:
        return None
    if cmd[0] == 'pgrep' and '-xq' in cmd:
        name = cmd[-1]
        browser = state.get('browser', state.get('front_app', ''))
        if name in (browser, state.get('front_app', '')):
            return subprocess.CompletedProcess(cmd, 0, '', '')
        if browser and name in ('Google Chrome', 'Safari', 'Arc', 'Brave Browser', 'Microsoft Edge'):
            return subprocess.CompletedProcess(cmd, 0, '', '')
        if name in ('Google Chrome', 'Safari', 'Arc', 'Brave Browser'):
            return subprocess.CompletedProcess(cmd, 1, '', '')
        return None
    if cmd[0] == 'osascript':
        script = ' '.join(cmd)
        if 'return (id of window' in script:
            return subprocess.CompletedProcess(cmd, 0, '10\t2', '')
        if 'get {name, bounds}' in script:
            return subprocess.CompletedProcess(cmd, 0, f'{state.get("front_window", "Fixture")}, 0, 0, 900, 700', '')
        if len(cmd) >= 3 and cmd[-1] and ('read' in cmd[-1] or 'click' in cmd[-1] or 'fill' in cmd[-1] or 'ready' in cmd[-1] or 'name' in cmd[-1]):
            parsed = _web_js_payload(cmd[-1])
            if parsed:
                out = _web_reply(*parsed, state)
                return subprocess.CompletedProcess(cmd, 0, out, '')
        if 'document.title' in script:
            page = _page(state)
            return subprocess.CompletedProcess(cmd, 0, page.get('title', '') + ' ' + state.get('url', ''), '')
        return subprocess.CompletedProcess(cmd, 0, '', '')
    if cmd[0] in ('open', '/usr/bin/open'):
        target = cmd[-1]
        _log('open', {'target': target})
        if target.startswith('-'):
            return None
        return subprocess.CompletedProcess(cmd, 0, '', '')
    if cmd[0] == 'curl' and 'wttr.in' in ' '.join(cmd):
        return subprocess.CompletedProcess(cmd, 0, 'Fixture: Sunny +20°C', '')
    me = os.environ.get('ATTICUS_EVAL_ME', '')
    if me and me in cmd[0]:
        return None
    app = os.environ.get('ATTICUS_APP', '')
    if app and cmd[0] == app and len(cmd) > 2 and cmd[1] == '--window-target':
        target = {'pid': state.get('pid', 4242), 'windowID': '99', 'windowFrame': [0, 0, 900, 700],
                  'app': cmd[2], 'window': state.get('front_window', 'Fixture')}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(target), '')
    if app and cmd[0] == app and len(cmd) > 2 and cmd[1] == '--text':
        text = _ocr_text(state)
        _log('text_read', {'app': cmd[2], 'via': 'ocr'})
        return subprocess.CompletedProcess(cmd, 0, text, '')
    if app and cmd[0] == app and len(cmd) > 2 and cmd[1] == '--look':
        path = cmd[3] if len(cmd) > 3 else cmd[2]
        Path(path).write_bytes(b'\xff\xd8\xff\xd9')
        _log('look', {'path': path})
        return subprocess.CompletedProcess(cmd, 0, '', '')
    if cmd[0] == 'screencapture' and '-t' in cmd:
        path = cmd[-1]
        Path(path).write_bytes(b'\xff\xd8\xff\xd9')
        _log('look', {'path': path, 'via': 'screencapture'})
        return subprocess.CompletedProcess(cmd, 0, '', '')
    if cmd[0] == 'sips':
        return subprocess.CompletedProcess(cmd, 0, '', '')
    return None


def popen(args, **kwargs):
    app = os.environ.get('ATTICUS_APP', '')
    if not app or not args or args[0] != app or len(args) < 2 or args[1] != '--hands':
        return None
    state = _load()
    hand_args = list(args[2:])
    stdin_pipe = kwargs.get('stdin') == subprocess.PIPE

    def finish(receipt_json=None):
        ha = hand_args
        if ha[:1] == ['label']:
            return _hands_label(ha[1:], state), 0
        if receipt_json:
            try:
                ha = json.loads(receipt_json).get('args', ha)
            except ValueError:
                pass
        return _hands_act(ha, state), 0

    if hand_args[:1] == ['read']:
        out = _hands_read(hand_args[1:], state)
        return _FakeProc(args, out, returncode=0, stdin_pipe=stdin_pipe)
    if hand_args[:1] == ['label'] or hand_args[:1] == ['see']:
        out, code = finish()
        return _FakeProc(args, out, returncode=code, stdin_pipe=stdin_pipe)
    if (kwargs.get('env') or os.environ).get('ATTICUS_HANDS_SESSION') == '1':
        return _SessionProc(args, _hands_label(hand_args, state), finish)

    proc = _FakeProc(args, '', returncode=0, stdin_pipe=stdin_pipe)

    def communicate(input=None, timeout=None):
        out, code = finish(input)
        proc._buf, proc.returncode = out, code
        return out, proc._stderr

    proc.communicate = communicate
    return proc
