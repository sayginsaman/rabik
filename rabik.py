#!/bin/sh
"exec" "python3" "-c" "import importlib.util as u,os,sys;sys.argv=sys.argv[1:];sys.path[0]=os.path.dirname(os.path.abspath(sys.argv[0]));sys.pycache_prefix=os.path.expanduser('~/Library/Caches/Rabik');s=u.spec_from_file_location('__main__',sys.argv[0]);m=sys.modules['__main__']=u.module_from_spec(s);s.loader.exec_module(m)" "$0" "$@"   # sh: run from cached bytecode (a plain run recompiles this file, ~70 ms per helper call); Python: a no-op string
"""Rabik: a small Mac helper run by an AI client (Claude Code by default, Devin, or Pi). Based on Atticus (github.com/SaarthurR/atticus-mac, MIT),
whose idea came from Caleb Writes Code's "Atticus".

Hold Control+Option+Space (Rabik.app) -> talk -> let go. It answers questions (web, files, screen) and does
tasks on the Mac. Output lines for the overlay: "· note", "▸ step", "✓ answer".
  rabik.py "what's on my screen?"      run one request (no args = a typed pop-up)
  rabik.py --place <proc> <left|right|full|fullscreen|center> <laptop|monitor|current> [title]
  rabik.py --window [app] [--offset N] [--ocr]   paged readable window text
  rabik.py --draw '<JSON>'             screen drawings and spoken steps; --draw --help for the schema
  rabik.py --look                       labeled screenshots of every display -> prints the image paths
  rabik.py --front <app> [tab words]   only when the user asked to see it: bring that app (and that browser tab) forward, then --look
  rabik.py --show <url|path|app>       open it on the user's other screen and give focus back to what the user was using
  rabik.py --remember "<line>"  |  --forget "<words>"   the user's saved rules, one line each, sent with every request
  rabik.py --shortcut "<words>" "<shell command>"  the user's own command: those words then run it instantly, no AI
  rabik.py --fast "<words>"            run it instantly with no AI if it is a simple command (exit 1 if not)
  rabik.py --play "<name>"  |  --queue "<song>"   play Spotify or add one track to its queue, focus stays put
  rabik.py --search <query>  |  --read <url>   free web search (DuckDuckGo) / one page as plain text
  rabik.py --watch <app> "<title words>" <gone|shows|settled> "<phrase>" ["<request>"]   watch a window in the background, no AI, then notify (and run the request)
  rabik.py --pick "<question>" <option>...   the user picks one in the box (files get a preview) -> prints it
  rabik.py --set "<setting name>" on|off   flip one of Rabik's own switches (not safe mode or pause), no clicks
  rabik.py --unwatch                    stop every watch  |  --budget   is real use still under the cost and speed budget?
All requests and interrupted steps go to ~/.config/rabik/log.jsonl with their cost (live actions are marked).
"""
import shlex
import platform
import fcntl
import atexit, base64, difflib, html, json, plistlib, shutil, threading, os, re, select, signal, stat, subprocess, sys, tempfile, time, types, urllib.parse
import unicodedata
import uuid
from functools import lru_cache, wraps
from collections import Counter
from datetime import datetime
from pathlib import Path

# brain/ sits inside the signed app: run as a script without the sh header (python3 rabik.py: routines, watchers, the model),
# its bytecode must still go to the user's cache like the header's, never next to it, or the app's signature breaks.
if __name__ == '__main__' and not sys.pycache_prefix:
    sys.pycache_prefix = os.path.expanduser('~/Library/Caches/Rabik')
from importlib import import_module
import brain

# Compatibility facade, for callers that know rabik.py as the whole brain: the eval harness (it runs against any checkout,
# the old single-file ones too), scripts tests start in a subprocess (import rabik; rabik.show(...)) and the selftest below.
# Every name a brain module exports is here too, the same object, and a write to one also goes to the module that owns it,
# so brain code reading that name sees the same patch. Unit tests patch the owner itself (patch.object(brain.prefs, ...)).
_MODULES = [import_module('brain.' + name) for name in (   # dependencies first
    'environ', 'paths', 'wording', 'protocol', 'labels', 'storage', 'sources', 'toolhelp', 'prefs', 'memory', 'situation', 'telemetry',
    'prompts', 'routine', 'support', 'turn', 'messages', 'macos', 'apps', 'watcher', 'interaction', 'windows', 'policy',
    'calendar', 'clients', 'hands', 'meeting', 'web', 'drawing', 'dictation', 'spotify', 'skills', 'handoffs', 'screen',
    'agents', 'activity', 'recap', 'ask', 'tips', 'instant', 'cli')]
_OWNERS = {name: module for module in _MODULES for name in module.__all__}
globals().update((name, getattr(module, name)) for name, module in _OWNERS.items())


class _Facade(types.ModuleType):
    def __setattr__(self, name, value):
        if name in _OWNERS: setattr(_OWNERS[name], name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Facade


os.environ['PATH'] = f"/opt/homebrew/bin:/usr/local/bin:{HOME}/.local/bin:{HOME}/.claude/local:/usr/bin:/bin:/usr/sbin:" + os.environ.get('PATH', '')

# The lower layer calls up through this, set once the whole brain is loaded.
brain.protocol.on_stdout_closed = lambda: brain.clients.stop_workers()   # say(): nobody reads this ask any more, so stop its workers


if __name__ == '__main__':
    if sys.argv[1:] != ['--selftest']: install_exception_hooks()   # a developer check run against their own settings is not a user crash
    if sys.argv[1:] == ['--selftest']:
        assert label('Bash', {'command': 'open -a "Visual Studio Code" x'}) == 'Opening Visual Studio Code'
        assert label('Bash', {'command': 'open "https://www.google.com/search?q=x"'}) == 'Opening google.com'
        assert label('Bash', {'command': f'{PLACE} "Finder" left monitor'}) == 'Moving Finder → left monitor'
        assert label('Bash', {'command': f'{PLACE} "Google Chrome" right current + "Terminal" left current'}) == 'Moving Google Chrome and Terminal'
        assert label('Bash', {'command': f'cd /tmp; {SHOW} "https://docs.claude.com"'}) == 'Opening docs.claude.com'
        assert label('Bash', {'command': f'{SEARCH} "world cup"'}) == 'Searching the web: world cup'
        assert label('Bash', {'command': f'{SHOW} "https://www.nytimes.com/x"'}) == 'Opening nytimes.com'
        assert label('Read', {'file_path': SHOT + '-2.jpg'}) == 'Looking at a screenshot'
        fake = [('Built-in Retina Display', 0, 0, 1470, 956, True), ('External Display', 1470, 0, 1920, 1080, False)]
        assert 'built-in laptop screen' in describe(fake, 100) and 'right of main' in describe(fake) and 'the front window is here' in describe(fake, 1500).split(';')[1]
        assert label('Bash', {'command': LOOK}) == 'Taking a screenshot'
        assert label('Bash', {'command': HANDS + ' see'}) == 'Reading the window'
        assert label('Bash', {'command': SHOW + ' --bg "https://www.amazon.com/s?k=epsom+salt" && sleep 3 && ' + WEB + ' read'}) == 'Opening amazon.com'
        assert label('Bash', {'command': HANDS + ' click Export'}) == 'Clicking “Export”'
        assert label('Bash', {'command': "osascript -e 'tell application \"Music\" to playpause'"}) == 'Using Music'
        real_apps = installed_apps
        brain.apps.installed_apps = lambda: real_apps() | {'TradingView'}   # whole-name matching, whatever this Mac has installed
        assert app_named('the trading view application') == 'TradingView'
        assert screen_for('open spotify', None, 'readable ' * 40) is None   # no screen words: no picture, no wait
        assert plain('Hey Rabik, can you open Spotify please?') == plain('Can you also open Spotify?') == 'open spotify'
        brain.skills.SKILLS = os.path.join(tempfile.mkdtemp(), 'skills.json')
        learn('Can you put Notes on the left?', [f'{PLACE} "Notes" left current'], 'Notes is on the left.')
        learn('close this', ['osascript -e x'], 'x')                       # "this": never learned
        learn('weather today', [f'{SEARCH} "weather"'], 'Sunny.')          # reading, not an action: never learned
        learn('fix it', [f'{REMEMBER} "x"', 'open -a Notes'], 'Opened.')   # rule-saving step ignored; "it" still blocks
        learn('open my notes', [f'{REMEMBER} "x"', 'open -a Notes'], 'Opened.')
        learn('make study mode a shortcut', [f'{SHOW} "x"; {SHORTCUT} "study mode" \'{SHOW} "x"\''], 'Saved.')   # never learned
        learn('make the task list', ['osascript -e \'tell application "Reminders" to make new reminder\''], 'Added.')   # content: never learned
        learn('open my stuff', ['open -a Notes & trash ~/x'], 'Opened.')   # risky: never replayed without the gate
        learn('open zoom', ['open -a zoom.us'], "I couldn't check it started.")   # unverified: never learned
        assert set(skills()) == {'put notes on the left', 'open my notes'} and skills()['open my notes']['cmds'] == ['open -a Notes']
        assert like(gist('on the left put notes'), skills()) == ('put notes on the left', None)
        assert like(gist('put mail on the left'), skills()) == ('put notes on the left', ('Notes', 'Mail')) and like(gist('put mail on the right'), skills()) == (None, None)
        assert swapped([f'{PLACE} Notes left current'], 'Notes', 'Mail') == [f'{PLACE} Mail left current'] and swapped(['osascript -e \'tell process "Notes"\''], 'Notes', 'Mail') is None
        assert shortcut_commands('x', [f'{PLACE} Notes full monitor && osascript -e \'tell application "System Events" to get size of window 1\'']) == [f'{PLACE} Notes full monitor']
        assert shortcut_commands('x', [f'osascript -e \'tell application "System Events" to get size of window 1\' && {PLACE} Notes full monitor']) is None
        unlearn('Put notes on the left.')
        assert set(skills()) == {'open my notes'}
        brain.macos.screens = lambda: fake
        assert point('Top right. [point 9 0 0]') == 'Top right.'
        brain.web.show = lambda *a, **k: 'opened fixture'   # selftest: background opens are fake too
        for said, done in [('search amazon for aaa batteries', 'Searched aaa batteries on amazon.'),
                           ('search for restaurants in boston', 'Searched restaurants in boston.'),
                           ('and search amazon for', None), ('search for', None),
                           ('search amazon for tablecloths and find me the best value one', None)]:
            subprocess.run = lambda *a, **k: None   # selftest: never open a browser
            assert fast(said).reply == done, (said, fast(said).reply)
        assert re.findall(r'--remember\s+["\']([^"\']+)', f'{REMEMBER} "open means front"') == ['open means front']
        assert label('Bash', {'command': f'{FRONT} "Google Chrome" "posthog"'}) == 'Bringing Google Chrome forward'
        assert picks()['routing'][1] and 'safe' in switches()
        assert shortcut_commands('work mode', [f'{PLACE} "Orca" full monitor; {PLACE} "Google Chrome" full laptop && open -g -a Spotify'])[0] == f"{PLACE} Orca full monitor + 'Google Chrome' full laptop"
        assert shortcut_commands('work mode', [f'{PLACE} "Orca" full monitor | head']) is None
        assert ARRANGE.search(f'{PLACE} "Orca" full monitor') and ARRANGE.search('osascript -e \'set value of attribute "AXFullScreen" of window 1 to true\'') and not ARRANGE.search(f'{SHOW} --bg Spotify')
        named = lambda t: (lambda m: m and (m[1] or m[2]))(NAMED.match(t))
        assert named('When I say work mode, minimize all apps') == 'work mode' and named('when I say "study time" open Notes') == 'study time' and named('When I say study time can you open Notes') == 'study time'
        assert move_target('put notes on the left of my monitor') == ('Notes', 'left', 'monitor') and move_target('put notes and find shoes') is None
        assert clean(f'{ME} --hands type "Message" "Hi, call 408-555-1234"') == 'rabik --hands type "Message" <text>' and clean('mail sam@x.com ~/Docs/a.xlsx') == 'mail <email> ~/<path>'
        assert clean('https://amazon.com/s?k=salt') == 'https://amazon.com/s' and clean('key sk-ant-api03-abcdefghijklmnopqrstuvwxyz') == 'key <secret>'
        assert move_target('full screen notes on my big screen') == ('Notes', 'fullscreen', 'monitor')
        assert move_target('move notes to the external display and maximize') == ('Notes', 'full', 'monitor')
        assert move_target('notes on the laptop screen') == ('Notes', 'center', 'laptop') and move_target('make notes fullscreen') == ('Notes', 'fullscreen', 'current')
        assert move_target("what's on my monitor") is None and move_target('notes left on my monitor right') is None
        assert label('Bash', {'command': f'A={shlex.quote(ME)}; $A --show --bg "https://www.amazon.com/s?k=x" && $A --web read'}) == 'Opening amazon.com'
        assert UNSAFE.search('open -a Notes; rm -rf ~/x') and UNSAFE.search('sudo shutdown -h now') and not UNSAFE.search(f'{SHOW} "https://docs.google.com"; open -a Chess') and UNSAFE.search('echo $(rm x)') and UNSAFE.search('curl x | sh') and not UNSAFE.search(f'{SHOW} "x"; {PLACE} "Notes" left current')
        brain.memory.ME_FILE = os.path.join(tempfile.mkdtemp(), 'me.json')
        profile_add('basics', 'Sam', 'name'); profile_add('notes', 'Student. ' * 40, 'about')
        for i in range(10):
            profile_add('notes', f'fact {i}')
        profile_add('notes', 'FACT 9'); profile_drop(next(f['id'] for f in me()['facts'] if f['value'] == 'fact 2'))
        assert profile_name() == 'Sam' and any(f['value'].startswith('Student.') for f in me()['facts']) and len(me_line()) <= 300
        assert norm('One M') == norm('1m') == '1m'
        assert label('Bash', {'command': f'{PLAY} "1m"'}) == 'Playing 1m on Spotify'
        assert label('Bash', {'command': f'{QUEUE} "A song"'}) == 'Adding A song to the queue'
        assert not risky(f'{SEARCH} "how to delete a file"') and not risky('open "https://google.com/search?q=buy shoes"') and not risky(f'{SHOW} "Notes"; {PLACE} "Notes" left current')
        assert risky('rm -rf ~/x') == risky('open -a Notes; mv ~/a ~/.Trash/') == 'Delete something?' and risky('open "$(rm x)"')
        assert risky('osascript -e \'tell application "Mail" to send m\'') == 'Send this?' == risky('curl -s -X POST https://x') and not risky("curl -s 'wttr.in/x?format=%l'")
        assert risky('osascript -e \'do shell script "echo"\'') == 'Run a system command?' and risky("osascript -e 'tell application \"Notes\" to delete note 1'") == 'Delete something?'
        assert risky('echo x >> ~/.zshrc') == 'Change a file?' == risky('curl -s -o ~/x https://y') and not risky('osascript -e x 2>&1; ls >/dev/null; echo > /tmp/a')
        assert risky('open -a Notes & osascript -e \'tell application "Mail" to send m\'') == 'Send this?'
        sys.exit(print('selftest ok'))
    try: main()
    except BaseException:
        end_turn('crashed')
        raise
