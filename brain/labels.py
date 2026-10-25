"""Step labels for the box ("Opening google.com", "Clicking “Export”"), read from the commands an ask runs."""
import json
import os
import re
import shlex
import urllib.parse
from brain import paths

__all__ = ['KEYS', 'hands_name', 'hands_label', 'on_spotify', 'label']


def on_spotify(name):
    return name if re.search(r'\bspotify\b', name, re.I) else name + ' on Spotify'   # Spotify's own playlists end in "on Spotify"


def label(name, inp):
    """Turn a tool call into a short line for the overlay."""
    if name == 'WebSearch':
        return 'Searching the web: ' + inp.get('query', '')
    if name == 'WebFetch':
        return 'Reading ' + re.sub(r'^https?://(www\.)?([^/]+).*', r'\2', inp.get('url', ''))
    if name == 'Read':
        return 'Looking at a screenshot' if os.path.basename(inp.get('file_path', '')).startswith(os.path.basename(paths.SHOT)) else 'Reading ' + os.path.basename(inp.get('file_path', ''))
    word = r"""(?:'[^']*'|"[^"]*"|\S+)"""   # a shell word: a quoted path may hold spaces
    c = re.sub(r'^cd ' + word + r'\s*(;|&&)\s*', '', ' '.join(inp.get('command', '').split()))   # "cd /tmp; <helper>" reads as the helper
    v = re.match(r'(\w+)=(' + word + r')\s*(?:;|&&)\s*', c)   # "A=<helper>; $A --web read" reads as the helper
    if v:
        value = shlex.quote(v[2][1:-1]) if v[2][:1] in '\'"' else v[2]   # quoted the way the helper constants are
        c = re.sub(r'"?\$\{?' + v[1] + r'\b\}?"?', lambda _: value, c[v.end():])
    try: words = shlex.split(c)
    except ValueError: words = []
    if len(words) > 2 and os.path.basename(words[0]) == 'open' and os.path.basename(words[1]) == 'rabik.py':
        return 'Reading the window' if words[2] == '--window' else 'Working on it'
    first = re.split(r'\s+(?:[\d&]*>|\||&&|;)', c)[0]   # "--search q 2>&1 | head" reads as the search
    if c.startswith(paths.SEARCH):
        return 'Searching the web: ' + first[len(paths.SEARCH):].strip(' "\'')
    if c.startswith(paths.READ):
        return 'Reading ' + re.sub(r'^https?://(www\.)?([^/]+).*', r'\2', first[len(paths.READ):].strip(' "\''))
    if c.startswith(paths.SHOW):
        try: args = shlex.split(c[len(paths.SHOW):])
        except ValueError: return 'Opening a window'
        t = next((a for a in args if a != '--bg'), '')
        if not t or t in ('&&',';','||','|'): return 'Opening a window'
        return 'Opening ' + (re.sub(r'^www\.', '', urllib.parse.urlparse(t).hostname or '') if '://' in t else os.path.basename(t))
    if c.startswith(paths.ABOUT):
        return 'Noting that about you'
    if c.startswith(paths.REMEMBER):
        return 'Remembering that'
    if c.startswith(paths.SHORTCUT):
        return 'Saving your shortcut'
    if c.startswith(paths.FORGET):
        return 'Forgetting that'
    if c.startswith(paths.PICK):
        return 'Asking you which one'
    if c.startswith(paths.SET):
        return 'Changing a setting'
    if c.startswith(paths.PLAY):
        return 'Playing ' + on_spotify(c[len(paths.PLAY):].strip(' "\''))
    if c.startswith(paths.QUEUE):
        return 'Adding ' + c[len(paths.QUEUE):].strip(' "\'') + ' to the queue'
    if c.startswith(paths.DRAW):
        return 'Getting ready to draw' if '--help' in words else 'Drawing on your screen'
    if c.startswith(paths.LOOK):
        return 'Taking a screenshot'
    if c.startswith(paths.WEB):
        return {'read': 'Reading the page', 'click': 'Clicking', 'fill': 'Filling it in', 'type-after': 'Typing at the answer'}.get((c[len(paths.WEB):].split() or [''])[0], 'Using the page')
    if c.startswith(paths.WINDOW):
        return 'Reading the window'
    if c.startswith(paths.HANDS):   # a chain reads as one line: Clicking “File › Export” → Typing into “Name”
        return ' → '.join(hands_label(p.strip(' ;&|')) for p in c.split(paths.HANDS)[1:])
    if c.startswith(paths.HISTORY):
        return 'Checking what you asked before'
    if c.startswith(paths.FRONT):   # the app is the first word of this command, never a quoted word later in the chain
        try: app = shlex.split(first[len(paths.FRONT):])[:1]
        except ValueError: app = []
        return 'Bringing ' + (app or ['the app'])[0] + ' forward'
    if c.startswith(paths.PLACE):
        many = re.findall(r'"([^"]+)"\s+(?:left|right|full|center)', c)
        if len(many) > 1:
            return 'Moving ' + ', '.join(many[:-1]) + ' and ' + many[-1]
        a = c[len(paths.PLACE):].replace('"', '').split()
        return f'Moving {a[0]} → {" ".join(a[1:3])}' if a else 'Moving a window'
    m = re.match(r'^open (?:-g )?-a (?:"([^"]+)"|(\S+))', c)
    if m:
        return 'Opening ' + (m[1] or m[2]).rstrip(';')
    for pat, fmt in ((r'^open "?https?://(?:www\.)?([^/"]+)', 'Opening {}'),
                     (r'^mdfind', 'Searching your files'), (r'arxiv', 'Searching papers'), (r'^pbpaste', 'Reading the clipboard'),
                     (r'tell application "(?!System Events)([^"]+)"', 'Using {}'), (r'process "([^"]+)"', 'Checking {} windows')):
        m = re.search(pat, c)
        if m:
            return fmt.format(*m.groups())
    if c.startswith('open '):
        return 'Opening ' + os.path.basename(first[5:].strip('"\' '))
    for flag, text in (('calendar', 'Using your calendar'), ('contacts', 'Looking up contacts')):
        if c.startswith(f'{shlex.quote(paths.ME)} --{flag} '): return text
    return ' '.join(str(inp.get('description') or '').split())[:80].rstrip('.') or 'Working on it'   # the AI's own plain words for the tool; never the raw command


KEYS = {'cmd': '⌘', 'command': '⌘', 'shift': '⇧', 'option': '⌥', 'alt': '⌥', 'ctrl': '⌃', 'control': '⌃',
        'enter': '↩', 'return': '↩', 'tab': '⇥', 'esc': '⎋', 'escape': '⎋', 'space': 'Space', 'delete': '⌫'}


def hands_name(t):
    """A map id or a screen spot as the words a person would use."""
    if t.isdigit():
        try:
            with open(paths.hands_state()) as f:
                n = next((n for n in json.load(f).get('nodes', []) if n.get('id') == int(t)), {})
            return n.get('label') or re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', n.get('role', '').replace('AX', '')).lower() or 'that'
        except (OSError, ValueError, AttributeError):
            return 'that'
    return 'a spot on screen' if re.fullmatch(r'[\d:,. ]+', t) else t.replace(' > ', ' › ')


def hands_label(s):
    try:
        a = shlex.split(s)
    except ValueError:
        return 'Working on it'
    if a[:1] == ['menu'] and len(a) == 3: return 'Clicking ' + hands_name(a[2])
    verb = {'see': 'Reading the window', 'click': 'Clicking', 'scroll': 'Scrolling', 'scroll-to': 'Finding', 'press': 'Pressing',
            'drag': 'Dragging', 'type': 'Typing into', 'type-after': 'Typing after', 'wait': 'Waiting'}.get(a[0] if a else '', 'Working on it')
    if len(a) < 2 or a[0] in ('see', 'wait'):
        return verb
    if a[0] == 'scroll':
        return f'{verb} {a[1]}'
    if a[0] == 'press':
        return f'{verb} ' + ''.join(KEYS.get(k.lower(), k.upper() if len(k) == 1 else k.capitalize()) for k in a[1].split('+'))
    return f'{verb} “{hands_name(a[1])[:60]}”'
