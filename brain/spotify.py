"""Spotify: play a playlist, album or song, and queue one track, without taking focus."""
import difflib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from brain import hands, labels, macos, paths, web, windows, wording

__all__ = ['PLAYLISTS', 'playlist', 'spotify_item', 'play', '_spotify_ax_strings', '_spotify_control', '_spotify_wait_control',
           '_spotify_title_anchor', '_spotify_verified', 'queue']


PLAYLISTS = os.path.join(paths.DIR, 'playlists.json')


def playlist(name):
    """(uri, title) of a playlist in the user's Spotify app's cache whose title matches, else None."""
    names, fresh = {}, False
    try:
        with open(PLAYLISTS) as f:
            cached = json.load(f)
        if isinstance(cached, dict):
            names, fresh = cached, time.time() - os.path.getmtime(PLAYLISTS) < 3600
    except (OSError, ValueError):
        pass
    hit = lambda: next(((f'spotify:playlist:{i}', t) for i, t in names.items() if t and wording.norm(t) == wording.norm(name)), None)
    if hit() or fresh:
        return hit()   # rescan at most hourly: mid-speech checks call this on every word
    ids = set()   # not known yet: read every playlist id from the cache, name the new ones (once each, saved)
    for root, _, files in os.walk(os.path.join(paths.HOME, 'Library/Application Support/Spotify')):
        for f in files:
            try:
                ids |= set(re.findall(rb'spotify:playlist:([A-Za-z0-9]{22})', Path(root, f).read_bytes()))
            except OSError:
                pass
    new = [i.decode() for i in ids if not names.get(i.decode()) and not i.startswith(b'37i9')]   # 37i9… = Spotify's own mixes
    def title(i):
        try:
            return i, json.loads(web.get(f'https://open.spotify.com/oembed?url=https://open.spotify.com/playlist/{i}'))['title']
        except Exception:
            return i, ''
    from concurrent.futures import ThreadPoolExecutor
    names.update((i, t) for i, t in ThreadPoolExecutor(16).map(title, new) if t)
    os.makedirs(paths.DIR, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=paths.DIR, delete=False) as f:
        try:
            json.dump(names, f)
            f.flush(); os.fchmod(f.fileno(), 0o600); os.replace(f.name, PLAYLISTS)
        finally:
            if os.path.exists(f.name):
                os.unlink(f.name)
    return hit()


def spotify_item(name, anything=True):
    """The matching Spotify (uri, title), preferring an exact cached user playlist."""
    p = playlist(name)
    if not p and anything:
        try:
            for engine in ('https://html.duckduckgo.com/html/?q=', 'https://search.brave.com/search?q='):   # DDG misses some; Brave backs it up
                page = urllib.parse.unquote(web.get(engine + urllib.parse.quote(name + ' spotify')))
                m = re.search(r'open\.spotify\.com(?:/intl-\w+)?/(track|album|artist|playlist)/([A-Za-z0-9]{22})', page)
                if m:
                    break
            url = m and f'https://open.spotify.com/{m[1]}/{m[2]}'
            p = m and (f'spotify:{m[1]}:{m[2]}', json.loads(web.get('https://open.spotify.com/oembed?url=' + url))['title'])
            if p:
                asked, found = wording.norm(name), wording.norm(re.split(r'\s+[-–|]\s+', p[1], maxsplit=1)[0])
                if asked != found and not (len(asked) >= 5 and difflib.SequenceMatcher(None, asked, found).ratio() >= .9):
                    p = None
        except Exception:
            p = None
    return p


def play(name, anything=True):
    """Play the user's playlist by that name; else (anything=True) the top Spotify song, album or artist for it from the web."""
    p = spotify_item(name, anything)
    if not p: return None
    mine = macos.osa('tell application "System Events" to get name of first process whose frontmost is true')
    try:
        # Spotify reports "paused" for a moment after play track (longer while it launches): wait, then ask once more
        played = subprocess.run(['osascript', '-e', 'on run argv\ntell application "Spotify"\nrepeat with attempt from 1 to 2\n'
                                 'play track (item 1 of argv)\nrepeat 15 times\nif player state is playing then return "playing"\n'
                                 'delay 0.1\nend repeat\nend repeat\nreturn player state as text\nend tell\nend run', p[0]],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        played = None
    if not played or played.returncode or played.stdout.strip().lower() != 'playing':
        return f'Could not start {p[1]} in Spotify. Check Spotify’s Automation permission and try again.'
    macos.preview_app('Spotify', 'play')
    if not macos.wants_focus(): windows.keep_behind(mine, 'Spotify')   # Spotify raises itself when it starts a track
    return f'Playing {labels.on_spotify(p[1])}.'


def _spotify_ax_strings(m):
    return (m or {}).get('texts', []) + [n.get('label', '') for n in (m or {}).get('nodes', [])]


def _spotify_control(m, words, title=''):
    """Return the actual AX label for a Spotify control; never guess an unseen label."""
    hits = [n for n in (m or {}).get('nodes', []) if all(w in wording.plain(n.get('label', '')) for w in words)]
    if words == ('queue',):
        hits = [n for n in hits if 'add' not in wording.plain(n.get('label', ''))]
    if not hits: return None
    key = wording.norm(re.split(r'\s+[-–|]\s+', title, maxsplit=1)[0])
    if key:
        hits = [n for n in hits if ' for ' not in n.get('label', '').lower() or wording.norm(re.split(r'\s+for\s+', n['label'], maxsplit=1, flags=re.I)[-1]) == key]
    return max(hits, key=lambda n: wording.plain(n.get('label', '')) == ' '.join(words))['label'] if hits else None


def _spotify_wait_control(words, title='', first=None):
    for attempt in range(10):
        m = first if attempt == 0 and first else hands.hands_map('Spotify')
        label = _spotify_control(m, words, title)
        if label and (not title or _spotify_title_anchor(m, title)):
            return m, label
        time.sleep(.15)
    return None, None


def _spotify_title_anchor(m, title):
    key = wording.norm(re.split(r'\s+[-–|]\s+', title, maxsplit=1)[0])
    return next((s for s in _spotify_ax_strings(m) if wording.norm(s) == key), '')


def _spotify_verified(text, m, title='', action=False):
    strings = text.splitlines() + _spotify_ax_strings(m)
    key = wording.norm(re.split(r'\s+[-–|]\s+', title, maxsplit=1)[0])
    if key:
        identified = any(wording.norm(s) == key for s in strings)
        return identified and (not action or any('added' in wording.plain(s) and 'queue' in wording.plain(s) for s in strings))
    return any('added' in wording.plain(s) and 'queue' in wording.plain(s) for s in strings)


def queue(name):
    """Add one resolved Spotify track through its accessible controls without leaving Spotify in front."""
    p = spotify_item(name)
    if not p: return 'Nothing found on Spotify by that name.'
    parts = p[0].split(':', 2)
    if len(parts) != 3 or parts[1] != 'track':
        kind = parts[1] if len(parts) == 3 else 'item'
        return (f'Spotify does not expose the tracks in that {kind} to Rabik, so it cannot queue them in order. '
                'Name one song to add to the queue.')
    mine = macos.osa('tell application "System Events" to get name of first process whose frontmost is true')
    try:
        opened = subprocess.run(['open', '-g', p[0]], capture_output=True)
    except OSError:
        opened = None
    if not opened or opened.returncode:
        return f'Could not open {p[1]} in Spotify.'
    macos.preview_app('Spotify', 'queue')
    windows.keep_behind(mine, 'Spotify')
    m, more = _spotify_wait_control(('more', 'option'), p[1])
    if not more:
        return f'Opened {p[1]} in Spotify, but could not find its More options control.'
    anchor = _spotify_title_anchor(m, p[1])
    result, ok = hands.hands('click', more, *(['near', anchor] if anchor else []))
    windows.keep_behind(mine, 'Spotify')
    if not ok:
        return f'Could not open More options for {p[1]}: {result}'
    m, add = _spotify_wait_control(('add', 'queue'), first=macos.cached_hands())
    if not add:
        return f'Opened More options for {p[1]}, but Spotify did not offer Add to queue.'
    result, ok = hands.hands('click', add)
    windows.keep_behind(mine, 'Spotify')
    if not ok:
        return f'Could not add {p[1]} to the Spotify queue: {result}'
    m = macos.cached_hands() or {}
    if not _spotify_verified(result, m, p[1], action=True):
        m, show_queue = _spotify_wait_control(('queue',), first=m)
        if show_queue:
            shown, shown_ok = hands.hands('click', show_queue)
            windows.keep_behind(mine, 'Spotify')
            m = macos.cached_hands() or {}
            if shown_ok and _spotify_verified(shown, m, p[1]):
                return f'Added {p[1]} to your Spotify queue.'
        return (f'Spotify accepted Add to queue for {p[1]}, but Rabik could not verify it. '
                'It may already be queued; do not retry blindly.')
    return f'Added {p[1]} to your Spotify queue.'
