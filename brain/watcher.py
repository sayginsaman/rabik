"""Background watches (--watch): poll a window without AI until it changes, then notify and maybe run a request."""
import os
import subprocess
import sys
import time
from brain import macos, paths

__all__ = ['WATCHING', 'notify', 'watch']


WATCHING = os.path.join(paths.DIR, 'watching')


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
