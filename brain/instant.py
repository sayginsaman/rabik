"""Instant commands: the no-AI path for simple asks (open, place, play, replay a shortcut)."""
import hashlib
import os
import re
import shlex
import subprocess
import time
import urllib.parse
from pathlib import Path
from brain import apps, hands, macos, paths, prefs, protocol, skills, spotify, telemetry, tips, web, windows, wording

__all__ = ['fast']


def fast(text):
    """Simple commands with no AI: learned shortcuts, open <app/site>, close <app>, snap/move <it/app> left/right/full/center, to laptop/monitor.
    Returns a reply, or None to hand the request to Haiku."""
    fast.cmds = []
    fast.shortcut = fast.failed = None
    text = text.strip()
    named = skills.named_shortcut(text)
    if named and prefs.pref('learn', True):
        if os.environ.get('RABIK_LIVE') == '1': return None
        name, action = (named[1] or named[2]).strip(), text[named.end():].strip(' ,:;')
        if hands.hands_command(wording.plain(action)) or skills.named_shortcut(action): return None
        reply = action and fast(action)
        if reply and skills.learn(name, fast.cmds, reply, text) is not None:
            output = fast.shortcut['output'] if fast.shortcut else [reply]
            fast.shortcut = {'key': wording.plain(name), 'commands': fast.cmds, 'output': output}
            tips.tip(reply, f'Learned: Say “{name}” any time.')
            return reply
        return None
    t = wording.plain(text)
    if t in ('report feedback', 'report a bug'):
        if os.environ.get('RABIK_LIVE') == '1': return None
        protocol.say('!', 'feedback')
        return 'Review your feedback before opening GitHub.'
    quick = hands.fast_hands(t)
    if quick:
        return quick
    m = re.fullmatch(r'remember how to (.+?)(?: for (?:the )?future)?', t)
    if m and prefs.pref('learn', True):
        if os.environ.get('RABIK_LIVE') == '1':
            return None
        return ('I have saved the procedure for next time.' if skills.workflows(m[1]) or any(wording.gist(k) == wording.gist(m[1]) for k in skills.skills()) else
                'I do not have a verified procedure for that yet. Complete the task successfully first so I can save it.')
    if t in ('no', 'yes', 'ok', 'okay', 'nevermind', 'never mind', 'cancel', 'nothing', 'thanks', 'thank you'):
        return None if os.environ.get('RABIK_LIVE') == '1' else 'Okay.'   # stray word after a turn: no AI call; mid-sentence it starts the next words ("No, when I say …")
    m = re.fullmatch(r'(?:close|quit) (.+)', t)
    app = apps.app_named(m[1]) if m and not wording.DEICTIC.search(m[1]) else None
    if app:
        bid = apps.app_id(app)
        if not bid:
            return None
        if not apps.quit_app(bid):
            return f'{app} is still open.'
        fast.cmds = [shlex.join(['osascript', '-e', f'tell application id "{bid}" to quit'])]
        return f'Closed {app}.'
    sk, g = (skills.skills() if prefs.pref('learn', True) else {}), wording.gist(t)
    k, swap = (t, None) if t in sk else (None, None) if wording.DEICTIC.search(t) or not g else skills.like(g, sk)   # same words that matter, any order or filler, or another app
    if k:
        if os.environ.get('RABIK_LIVE') == '1':
            return None   # even a shortcut named "open Spotify" waits for confirmed words
        r = skills.replay(k, swap)
        if r:
            fast.cmds = skills.replay.commands
            fast.shortcut = {'key': t if swap else k, 'commands': skills.replay.commands, 'output': skills.replay.ran}
            return r
        if skills.replay.ran:   # it acted, then a step failed or its check contradicted: never another instant reply, the AI redoes it
            fast.failed = {'key': k, 'commands': skills.replay.commands, 'output': skills.replay.ran, 'failed_at': skills.replay.failed_at}
            if telemetry.telemetry_enabled():
                telemetry.report_error('replay', shortcut=hashlib.sha256((telemetry.install_id() + '\0' + k).encode()).hexdigest()[:16],
                             failed_at=skills.replay.failed_at)
            return None
    site = re.fullmatch(r'(?:search(?: up)?|google|look up) ([a-z0-9][\w.-]*) for (.+)', t)
    m = site or re.fullmatch(r'(?:search(?: up)?|google|look up)(?: for)? (.+)', t)
    if site and apps.app_named(site[1]): site = m = None
    query = m[2] if site else m[1] if m else ''
    if query and not wording.DEICTIC.search(query) and not wording.MORE.search(query) and not re.search(r'\b(for|the|a|an|and|to|of|some)$', query):
        target = ('https://duckduckgo.com/?q=' + urllib.parse.quote_plus('!' + site[1] + ' ' + query, safe='!') if site else
                  'https://www.google.com/search?q=' + urllib.parse.quote(query))
        if not str(web.show(target, bg=True)).startswith('opened '):
            return None
        fast.cmds = [f'{paths.SHOW} --bg {shlex.quote(target)}']
        return f'Searched {query}' + (f' on {site[1]}.' if site else '.')
    m = re.fullmatch(r'play (?:my |the )?(?:spotify )?(?:playlist )?(?:called |named )?(.+?)( playlist)?( on spotify)?', t)
    if m and not wording.DEICTIC.search(m[1]) and not wording.MORE.search(m[1]):   # "play X" alone may mean a video: only the user's playlist here, anything else goes to the AI (which uses --play)
        reply = spotify.play(m[1], anything=bool(m[3]))
        if reply and reply.startswith('Playing '): fast.cmds = [f'{paths.PLAY} {shlex.quote(m[1])}']
        return reply
    m = re.fullmatch(r'(?:add|put) (.+?) (?:to|in|on) (?:my |the )?(?:spotify )?queue|queue (.+?)(?: next)?', t)
    name = (m[1] or m[2]).removeprefix('the song ').removeprefix('song ') if m else ''
    if name and not wording.DEICTIC.search(name) and not wording.MORE.search(name):
        reply = spotify.queue(name)
        if reply.startswith('Added '): fast.cmds = [f'{paths.QUEUE} {shlex.quote(name)}']
        return reply
    m = re.fullmatch(r'(?:open(?: up)?|launch|start|pull up|bring up|focus(?: on)?|switch to|go to)\s+(?!up$)(.+?)'
                     r'(?:\s+(?:on|to|in|at)\s+(?:the\s+|my\s+)?(left|right|full ?screen|center|middle|laptop|monitor)(?:\s+(?:side|half|screen))?)?', t)
    if m and m[2]:   # "open Chrome on my monitor": open it, then the move command below
        if not macos.asks_front(text): macos.free_focus(user=True)   # the inner "open" skips this, as if allow_focus had seen these words
        if not fast(f'open {m[1]}'):
            return None
        opened = fast.cmds[:]
        for _ in range(20):   # a just-launched app needs a moment for its window
            r = fast(f'move {m[1]} to {m[2]}')
            if r:
                fast.cmds = opened + fast.cmds
                return r
            time.sleep(0.1)
        return None
    if m:
        target = m[1]
        site = target.replace(' dot ', '.')
        site = next((w.rstrip('.,!?') for w in text.split() if wording.plain(w) == target), site)
        if re.fullmatch(r'(?:https?://)?[\w-]+(\.[\w-]+)+(/\S*)?', site) and not re.search(r'\.(pdf|docx?|xlsx?|pptx?|txt|csv|png|jpe?g|heic|key|pages|numbers|zip|mp[34]|mov|md|py|java)$', target):
            if not macos.asks_front(text): macos.free_focus(user=True)   # "go to", "launch", "pull up" ask to see it too; the guard must not pull it back
            try:
                opened = subprocess.run(['open', site if site.startswith(('https://', 'http://')) else 'https://' + site])
            except OSError:
                return None
            if opened.returncode:
                return None
            fast.cmds = ['open ' + shlex.quote(site if site.startswith(('https://', 'http://')) else 'https://' + site)]
            return f'Opened {target}.'
        app = apps.app_named(target) or apps.app_heard(target)
        if not app:
            return None
        if prefs.pref('openOn', 'here') == 'other':
            if not str(web.show(app)).startswith('opened '):   # Settings: open on the other screen and keep focus (slower, ~1-3 s)
                return None
        else:
            if not macos.asks_front(text): macos.free_focus(user=True)
            try:
                opened = subprocess.run(['open', '-a', app])   # plain open, ~0.1 s: here and in front
            except OSError:
                return None
            if opened.returncode:
                return None
        fast.cmds = [f'{paths.SHOW} {shlex.quote(app)}']
        Path(paths.LAST).write_text(app)
        return f'Opened {app}.'
    parts = [wording.plain(p) for p in re.split(r'\s*(?:[,;]|\band then\b|\band\b|\bthen\b)\s*', text) if wording.plain(p)]
    if len(parts) > 1:   # "Chrome left, Terminal right": every part a move, or the AI does it all
        moves = [windows.move_target(p if re.match(r'(snap|move|put|throw|send|make)\b', p) else 'put ' + p) for p in parts]
        if all(moves):   # else maybe one move said in parts: "full screen, chrome on my big screen"
            out = windows.place_many([x for a, w, sc in moves for x in ('+', apps.proc_of(a), w, sc)][1:])   # as --place a + b does
            if windows.place_failed(out): return None
            if 'could not check' in out: return windows.model_note(out)
            fast.cmds = [paths.PLACE + ' ' + ' + '.join(shlex.join([apps.proc_of(a), w, sc]) for a, w, sc in moves)]
            Path(paths.LAST).write_text(moves[-1][0])
            return '; '.join(f'{a}: {w.replace("fullscreen", "full screen")}' + (f' on {sc}' if sc != 'current' else '') for a, w, sc in moves) + '.'   # one sentence: a replay says the whole outcome
    m = windows.move_target(t)
    if not m:
        return None
    app, where, screen = m
    out = windows.place(apps.proc_of(app), where, screen)
    if windows.place_failed(out):
        return None
    if 'could not check' in out: return windows.model_note(out)
    fast.cmds = [paths.PLACE + ' ' + shlex.join([apps.proc_of(app), where, screen])]
    Path(paths.LAST).write_text(app)
    return f'{app}: {where.replace("fullscreen", "full screen")}' + (f' on {screen}' if screen != 'current' else '') + '.'
