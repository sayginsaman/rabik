"""Background watches (--watch): poll a window without AI until it changes, then notify and maybe run a request. And watches that
press a button whenever it shows (--watch press): Rabik.app runs those (App/AutoPress.swift) from watches.json until the user stops them."""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from brain import macos, paths, storage

__all__ = ['WATCHING', 'PRESS_NEVER', 'notify', 'watch', 'watches_path', 'press_watches', 'watch_press', 'watch_stop', 'watch_list']


WATCHING = os.path.join(paths.DIR, 'watching')


# A watch never presses these by itself, whatever the user said: they lose data or money with nobody looking.
PRESS_NEVER = re.compile(r'\b(delete|erase|remove|format|empty trash|pay|purchase|buy|transfer|wipe|reset|uninstall)\b', re.I)


def watches_path():
    return os.path.join(paths.DIR, 'watches.json')


def press_watches():
    """[{id, kind: 'press', app, labels, created}]: the button watches Rabik.app runs."""
    try:
        with open(watches_path()) as f: rows = json.load(f)
    except (OSError, ValueError): return []
    return [r for r in rows if isinstance(r, dict) and r.get('kind') == 'press' and re.fullmatch(r'[a-f0-9]{8}', str(r.get('id', ''))) and
            isinstance(r.get('app'), str) and r['app'] and isinstance(r.get('labels'), list) and r['labels']] if isinstance(rows, list) else []


def watch_press(app, labels):
    """--watch press "<app>" "<button>[|<button>]": the user confirmed it on a card (policy.RISKY). Runs until they stop it."""
    app = ' '.join(str(app).split())[:80]
    names = [' '.join(n.split())[:40] for n in str(labels).split('|') if n.strip()][:4]
    if not app or not names: raise ValueError('Name the app and the button, like: --watch press "ChatGPT" "Allow".')
    if any(PRESS_NEVER.search(n) for n in names): raise ValueError('Rabik never presses a button like that by itself. Do it yourself when it shows.')
    if app.casefold() == 'rabik': raise ValueError("Rabik doesn't press its own buttons.")
    rows = press_watches()
    if any(r['app'].casefold() == app.casefold() and [l.casefold() for l in r['labels']] == [n.casefold() for n in names] for r in rows):
        return f'Already watching {app} for {" or ".join(names)}.'
    os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
    rows.append({'id': uuid.uuid4().hex[:8], 'kind': 'press', 'app': app, 'labels': names, 'created': time.time()})
    storage.private_json(watches_path(), rows)
    return f'Watching {app}: Rabik clicks “{"” or “".join(names)}” whenever it shows, until you say stop watching.'


def watch_stop(identifier=None):
    """Stops one button watch, or every one (with the window watches the caller stops itself). -> how many."""
    rows = press_watches(); kept = [r for r in rows if identifier and r['id'] != identifier]
    if len(kept) != len(rows): storage.private_json(watches_path(), kept)
    return len(rows) - len(kept)


def watch_list():
    """--watches: the button watches, then the one-time window watches still waiting."""
    lines = [f"{r['id']} · clicks “{'” or “'.join(r['labels'])}” in {r['app']} until stopped" for r in press_watches()]
    if os.path.isdir(WATCHING):
        for pid in os.listdir(WATCHING):
            try:
                with open(os.path.join(WATCHING, pid)) as f: lines.append(f'{pid} · once: {f.read()[:160]}')
            except OSError: pass
    return '\n'.join(lines) or 'No watches.'


def notify(text):
    macos.osa('on run argv\ndisplay notification (item 1 of argv) with title "Rabik" sound name "Glass"\nend run', text)


def watch(what, then, app='', words='', mode='', phrase=''):
    """Free while it waits: every 5 s, a shell test (`what`, exit 0 = done) or one window's text read on this Mac. No AI;
    the AI runs again only for `then`."""
    norm = lambda s: ' '.join(s.lower().split())
    phrase, hits, misses, end, last = norm(phrase), 0, 0, time.time() + 3 * 3600, None
    while time.time() < end:
        if app:
            r = subprocess.run([paths.APP, '--text', app, words], capture_output=True, text=True)
            if r.returncode and words:   # the words often name a tab, not the window (Orca, browsers): read the app's main window
                r = subprocess.run([paths.APP, '--text', app, ''], capture_output=True, text=True)
            misses = misses + 1 if r.returncode else 0
            if misses >= 3:
                return notify(f"Stopped watching {app}: can't read its window. It must stay open on this desktop (covered is fine, minimized is not).")
            text = norm(r.stdout)
            if mode == 'settled':   # done when the text stops changing: agents' busy words and timers change every second
                done, last = not r.returncode and bool(text) and text == last, text if not r.returncode else None
            else:
                done = not r.returncode and (phrase in text) == (mode == 'shows')
        else:
            done = subprocess.run(['/bin/sh', '-c', what], capture_output=True).returncode == 0
        hits = hits + 1 if done else 0
        if hits >= (4 if mode == 'settled' else 2):   # settled: 20 s unchanged; else twice in a row, so one bad read or flicker can't fire it
            notify(f'{app or what[:40]}: done.' + (f' Now: {then}' if then else ''))
            return then and subprocess.run([sys.executable, paths.ME, then])
        time.sleep(5)
    notify('Stopped watching after 3 hours.')
