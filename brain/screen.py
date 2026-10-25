"""Seeing the screen: labeled screenshots (--look) and a window's readable text (--window)."""
import atexit
import json
import os
import re
import subprocess
import tempfile
from brain import drawing, environ, hands, macos, paths, prefs, storage, turn, web

__all__ = ['look', 'screen_for', 'TEXT_PAGE', 'text_page', 'window_identity', 'window_summary', 'window_text']


def look(cleanup=True, window=None):
    """Every display, 1280 px wide -> [(path, label)]. Standalone CLI callers remove their own files.
    window (a window_target): only its display, with that window painted where it sits, covered or not."""
    from concurrent.futures import ThreadPoolExecutor
    target = ThreadPoolExecutor(1).submit(drawing.draw_target) if prefs.pref('draw', True) else None   # found while the displays are listed and captured
    scr = macos.screens()
    x, y, w, h = (window or {}).get('windowFrame') or (0, 0, 0, 0)
    home = next((i for i, s in enumerate(scr, 1) if s[1] <= x + w / 2 < s[1] + s[3] and s[2] <= y + h / 2 < s[2] + s[4]), None) if window else None
    def one(i):
        ask = environ.ask_dir()   # AI helper images belong to the request owner, not this short-lived process.
        fd, path = tempfile.mkstemp(prefix=f'rabik-screen-{i}-', suffix='.jpg', dir=ask)
        os.close(fd)
        os.remove(path)
        if cleanup and not ask:
            atexit.register(lambda: os.path.exists(path) and os.remove(path))
        # Rabik.app takes it, leaving its own box out; plain screencapture is the fallback (box included)
        r = subprocess.run([paths.APP, '--look', str(i), path] + ([str(window['windowID'])] if i == home else []), capture_output=True, text=True)
        if r.returncode:
            subprocess.run(['screencapture', '-x', '-D', str(i), '-t', 'jpg', path])
            subprocess.run(['sips', '-Z', '1280', '-s', 'formatOptions', '70', path], capture_output=True)
        s = scr[i - 1]
        painted = f', {window.get("app")} "{window.get("window")}" painted where it sits' + ('' if window.get('visible') else ' (hidden from the user)') if i == home and 'window' in r.stdout.split() else ''
        return path, f'Screen {i}: "{s[0]}" ({"built-in laptop screen" if s[5] else "external monitor"}{painted}; click spots as {i}:x,y in picture pixels)'
    shots = [r for r in ThreadPoolExecutor(len(scr) or 1).map(one, [home] if home else range(1, len(scr) + 1)) if os.path.exists(r[0])]
    if target:
        mappings = {}
        for path, label in shots:
            n = int(re.search(r'Screen (\d+)', label)[1])
            size = subprocess.run(['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', path], capture_output=True, text=True).stdout or ''
            dims = re.findall(r'pixel(?:Width|Height): (\d+)', size)
            if len(dims) == 2:
                mappings[str(n)] = {'frame': list(scr[n-1][1:5]), 'pixels': list(map(int, dims))}
        snapshot = os.path.join(environ.ask_dir(paths.DIR), 'draw-screens.json')
        try:
            if not mappings: raise ValueError('No captured displays')
            storage.private_json(snapshot, {'screens': mappings, 'target': target.result()})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            try: os.remove(snapshot)
            except OSError: pass
    return shots


TEXT_PAGE = 8000


def text_page(text, offset=0, incomplete=False):
    if offset < 0: return 'Use a nonnegative offset.'
    end = min(offset + TEXT_PAGE, len(text))
    tail = f'; {len(text) - end} cached chars remain; {paths.WINDOW} --offset {end}' if end < len(text) or incomplete else '; end'
    if incomplete: tail += '; more document text available'
    return text[offset:end] + f'\n[Read {offset}-{end} of {len(text)} chars{tail}]'


def window_identity(app):
    try:
        r = hands.hands_call(['identify', app] if app else ['identify'], timeout=1)
        if not r.returncode:
            value = json.loads(r.stdout)
            if isinstance(value.get('identity'), str): return value['identity']
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        pass
    return ''


def window_summary(app=''):
    """Cheap key-down context: bounded AX head only; never OCR, permission cards, or full document text."""
    app = app or environ.front_app() or macos.front()[0]
    try:
        r = hands.hands_call(['read', app] if app else ['read'], timeout=.4, head=True)
        state = json.loads(r.stdout) if not r.returncode else {}
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        state = {}
    summary = {k: state[k] for k in ('app', 'window', 'page', 'web', 'identity', 'incomplete') if k in state}
    summary['app'] = summary.get('app') or app
    summary['text'] = str(state.get('text', ''))[:1500]
    directory = environ.ask_dir(paths.DIR)
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        with open(os.path.join(directory, 'window-summary.json.tmp'), 'w') as f: json.dump(summary, f)
        os.chmod(os.path.join(directory, 'window-summary.json.tmp'), 0o600)
        os.replace(os.path.join(directory, 'window-summary.json.tmp'), os.path.join(directory, 'window-summary.json'))
    except OSError:
        pass
    return summary


def window_text(app='', offset=0, ocr=False):
    """One reader: DOM when supported, document AX otherwise, then existing window OCR."""
    if offset < 0: return 'Use a nonnegative offset.'
    app = app or environ.front_app() or macos.front()[0]
    directory = environ.ask_dir(paths.DIR)
    path = os.path.join(directory, 'window-text.json')
    if offset:
        try:
            with open(path) as f: saved = json.load(f)
            if saved['app'] == app and saved['ocr'] == ocr:
                if saved['source'] == 'dom': return web.web('read', str(offset), app=app)
                identity = window_identity(app)
                if not identity or identity != saved.get('identity'):
                    return 'The window changed. Read again at offset 0.'
                continuations = 0
                while saved.get('incomplete') and offset + TEXT_PAGE > len(saved['text']) and continuations < 4:
                    continuations += 1
                    r = hands.hands_call(['read', app, 'more'], timeout=15)
                    if r.returncode: return r.stdout.strip() or 'Document continuation unavailable. Read at offset 0 again.'
                    state = json.loads(r.stdout)
                    if state.get('identity') != identity: return 'The window changed. Read again at offset 0.'
                    chunk = str(state.get('text', ''))
                    if chunk: saved['text'] += ('\n' if saved['text'] else '') + chunk
                    saved['incomplete'] = state.get('incomplete', False)
                    with open(path + '.tmp', 'w') as f: json.dump(saved, f)
                    os.chmod(path + '.tmp', 0o600); os.replace(path + '.tmp', path)
                    if not chunk: break
                return text_page(saved['text'], offset, saved.get('incomplete', False))
        except subprocess.TimeoutExpired: return 'Document continuation timed out. Read again or use --ocr/--look.'
        except (OSError, ValueError, KeyError): pass
        return 'Read the window at offset 0 first.'
    text, source, incomplete, identity, state = '', 'ax', False, '', {}
    web_hint = None
    for folder in dict.fromkeys((directory, paths.DIR)):
        try:
            with open(os.path.join(folder, 'window-summary.json')) as f: hint = json.load(f)
            if hint.get('app') == app:
                web_hint = (True if hint.get('web') else False if hint.get('incomplete') is False else None) if 'web' in hint else None
                break
        except (OSError, ValueError, AttributeError):
            pass
    if not ocr and web_hint is True:
        page = web.web('read', app=app, fresh=not bool(environ.agent()))
        if re.search(r'\[Read 0-\d+ of \d+ chars', page) or '\nControls:' in page or page.startswith('Controls:'):
            text, source = page, 'dom'
    if turn.STOPPING: return ''
    if not text and not ocr:
        try:
            r = hands.hands_call(['read', app], timeout=15)
            if r.returncode == 0:
                state = json.loads(r.stdout); text = state['text']; incomplete = state.get('incomplete', False); identity = state.get('identity', '')
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired): pass
        # No fresh key-down head for this app (a later step, another app): the full AX read says if it holds a web page.
        if web_hint is None and state.get('web') and not turn.STOPPING:
            page = web.web('read', app=app, fresh=not bool(environ.agent()))
            if re.search(r'\[Read 0-\d+ of \d+ chars', page) or '\nControls:' in page or page.startswith('Controls:'):
                text, source = page, 'dom'
    if turn.STOPPING: return ''
    if ocr or not text.strip():
        identity = identity or window_identity(app)
        try:
            r = subprocess.run([paths.APP, '--text', app, ''], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                text, source, incomplete = 'OCR (visible window text only):\n' + r.stdout.strip(), 'ocr', False
        except (OSError, subprocess.TimeoutExpired): pass
    os.makedirs(directory, mode=0o700, exist_ok=True)
    with open(path + '.tmp', 'w') as f: json.dump({'app': app, 'source': source, 'ocr': ocr, 'text': text, 'incomplete': incomplete, 'identity': identity}, f)
    os.chmod(path + '.tmp', 0o600); os.replace(path + '.tmp', path)
    return text if source == 'dom' else text_page(text, offset, incomplete) if text or incomplete else ''


def screen_for(task, snap, text=''):
    """Thin text can need a picture; semantic visual requests can use --look."""
    if prefs.pref('screen', 'auto') == 'never' or text.strip():
        return None
    if snap is None: return None
    if getattr(snap, 'started', False) is not True: return None
    if getattr(snap, 'is_alive', lambda: False)(): return None
    return list(snap.shots)
