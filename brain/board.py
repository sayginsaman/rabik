"""The live board (ui/board.html, Board.swift): a reply that starts with [board <layout>: <title>] is drawn on a card while
Rabik speaks it. The model writes one small command per line; each complete line is checked here and sent to the app as
"◫ {json}" while the reply still streams, so drawing starts with the first line. Unknown or invalid lines are dropped: the
model never runs code. The spoken lines become the answer the box shows and history keeps."""
import json
import re
from brain import environ, prefs, protocol

__all__ = ['BOARD_LAYOUTS', 'BOARD_SHAPES', 'BOARD_COLORS', 'BOARD_MATERIALS', 'board_line', 'BoardStream', 'board_stream', 'board_reply',
           'board_context', 'board_spoken']


BOARD_LAYOUTS = ('flow', 'cycle', 'mind', 'compare', 'timeline', 'chart', '3d')
BOARD_SHAPES = ('box', 'roundbox', 'sphere', 'dome', 'capsule', 'cylinder', 'pipe', 'cone', 'torus', 'wedge')
BOARD_MATERIALS = ('plastic', 'matte', 'rubber', 'metal', 'glass', 'glow')
MATERIAL_COLOR = {'glass': '#dcebf2', 'metal': 'silver', 'rubber': 'black', 'glow': 'yellow', 'matte': 'gray', 'plastic': 'gray'}
BOARD_COLORS = ('red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple', 'pink', 'brown', 'gray', 'black', 'white', 'silver', 'gold',
                'steel', 'copper', 'chrome', 'navy', 'cream', 'wood', 'skin')
OPEN = re.compile(r'\[board(\+)?(?:\s+([a-z0-9]+))?\s*:?\s*([^\]\n]*)\]\s*', re.I)
MOST = {'say': 40, 'mark': 90, 'column': 4}


def _text(value, limit):
    value = ' '.join(re.sub(r'(\*\*|__|`|^#+\s*)', '', value).split()).strip()
    return value[:limit].rstrip() if value else None


def _numbers(value, count, low, high):
    try: out = [float(x) for x in value.replace(' ', '').split(',')]
    except ValueError: return None
    return out if len(out) == count and all(low <= x <= high for x in out) else None


def _color(value):
    value = value.strip().lower()
    return value if value in BOARD_COLORS or re.fullmatch(r'#[0-9a-f]{6}', value) else None


def board_line(line):
    """One board command → an event for the page, or None. Opening and closing lines are handled by BoardStream."""
    line = line.strip()
    if line.startswith(('- ', '* ')): line = line[2:].strip()   # a model that bullets its commands
    word, _, rest = line.partition(' ')
    word, rest = word.lower().rstrip(':'), rest.strip()
    if not rest: return None
    if word in ('say', 'title', 'note', 'check', 'formula', 'column'):
        text = _text(rest, {'say': 400, 'title': 80, 'column': 40}.get(word, 160))
        return {'op': word, 'text': text} if text else None
    if word == 'item':
        title, _, detail = rest.partition('|')
        title, detail = _text(title, 80), _text(detail, 160)
        return ({'op': 'item', 'text': title, **({'detail': detail} if detail else {})}) if title else None
    if word == 'bar':
        m = re.fullmatch(r'(.+?)\s*[=:]\s*(-?\d[\d,]*(?:\.\d+)?)\s*([%$€£₺]|[A-Za-z]{1,6})?', rest)
        if not m: return None
        label = _text(m[1], 40)
        try: value = float(m[2].replace(',', ''))
        except ValueError: return None
        return {'op': 'bar', 'text': label, 'value': value, **({'unit': m[3]} if m[3] else {})} if label and abs(value) < 1e12 else None
    if word == 'circle':
        return {'op': 'circle', 'n': int(rest)} if rest.isdigit() and 1 <= int(rest) <= 60 else None
    if word == 'part':
        bits = [b.strip() for b in rest.split('|')]
        if not 5 <= len(bits) <= 7: return None
        name, shape, at, size = _text(bits[0], 40), bits[1].lower(), _numbers(bits[2], 3, -50, 50), _numbers(bits[3], 3, .005, 50)
        color, rot, material = None, [0, 0, 0], None
        for extra in bits[4:]:   # a color, a material and a turn, in any order; an empty slot ("| |") is skipped
            if not extra: continue
            if extra.lower() in BOARD_MATERIALS and not material: material = extra.lower()
            elif _color(extra) and not color: color = _color(extra)
            elif _numbers(extra, 3, -360, 360) is not None: rot = _numbers(extra, 3, -360, 360)
            else: return None
        color = color or MATERIAL_COLOR.get(material)   # "| glass" alone: a material standing in for its color
        if not name or shape not in BOARD_SHAPES or not at or not size or not color: return None
        return {'op': 'part', 'text': name, 'shape': shape, 'at': at, 'size': size, 'color': color, 'rot': rot, **({'material': material} if material else {})}
    return None


class BoardStream:
    """Follows one reply as it streams: emits each complete, valid line once (and the spoken lines as the box's text)."""
    def __init__(self, emit=True):
        self.reset(emit)

    def reset(self, emit=None):
        if emit is not None: self.emit = emit
        self.state, self.used, self.spoken, self.counts, self.events, self.columns, self.prose = None, 0, [], {}, [], set(), []   # state: None (unknown), 'board', 'no', 'done'

    def _send(self, event):
        kind = 'say' if event['op'] == 'say' else 'column' if event['op'] == 'column' else 'mark'
        if kind == 'column':   # "column Renting" again goes back to that column: only new names count
            if event['text'].casefold() in self.columns: kind = None
            else: self.columns.add(event['text'].casefold())
        if kind and event['op'] != 'open':
            self.counts[kind] = self.counts.get(kind, 0) + 1
            if self.counts[kind] > MOST[kind]: return
        if event['op'] == 'say': self.spoken.append(event['text'])
        self.events.append(event)
        if self.emit:
            protocol.say('◫', json.dumps(event, ensure_ascii=False))
            if event['op'] == 'say': protocol.say('…', ' '.join(self.spoken))   # the box shows what is said, as it is said

    def feed(self, text, final=False):
        """The whole reply so far. Returns True while it is (or may still become) a board."""
        if self.state in ('no', 'done'): return self.state == 'done'
        lines = text.lstrip().split('\n')
        complete = lines if final else lines[:-1]
        if self.state is None:
            head = lines[0].strip()
            if head and not '[board'.startswith(head[:6].lower()): self.state = 'no'; return False
            if not complete: return True
            m = OPEN.fullmatch(complete[0].strip())
            if not m: self.state = 'no'; return False
            layout = (m[2] or '').lower()
            title = _text(m[3], 80) if m[3] else None
            if layout not in BOARD_LAYOUTS:   # "[board Marketing plan]": no layout word, it is the title
                title, layout = _text(' '.join(filter(None, [m[2], m[3]])), 80), 'flow'
            self.state, self.used = 'board', 1
            self._send({'op': 'open', 'layout': layout, 'title': title or '', 'append': bool(m[1])})
        for line in complete[self.used:]:
            self.used += 1
            if re.fullmatch(r'\s*\[/board\]\s*', line, re.I):
                self.state = 'done'; self._send({'op': 'end'}); return True
            event = board_line(line)
            if event: self._send(event)
            elif line.strip(): self.prose.append(line.strip())   # not a command: kept in case nothing is said
        if final and self.state == 'board': self.state = 'done'; self._send({'op': 'end'})
        return True


board_stream = BoardStream(emit=False)   # the ask's live stream (ask.py turns emitting on in the box)


def board_spoken(reply):
    """A board reply's spoken lines, as plain answer text (for a reply that never streamed)."""
    stream = BoardStream(emit=False)
    stream.feed(reply, final=True)
    return ' '.join(stream.spoken)


def board_reply(reply):
    """The final reply: a board's remaining lines go to the app, and the answer becomes what was said."""
    if not re.match(r'\s*\[board', reply or '', re.I): return reply
    stream = board_stream if board_stream.state in ('board', 'done') else BoardStream(emit=environ.in_box() and prefs.pref('board', True))
    stream.feed(reply, final=True)
    if stream.state == 'no': return reply   # "[Board of directors] meet…": not a board after all
    return ' '.join(stream.spoken) or ' '.join(stream.prose) or 'It’s on the board.'


def board_context(board):
    """The board on screen (Rabik.app sends it with a follow-up), as data for the model."""
    if not isinstance(board, dict): return ''
    items = [str(i)[:80] for i in board.get('items', []) if isinstance(i, str)][:30]
    title, layout = str(board.get('title', ''))[:80], str(board.get('layout', ''))[:10]
    return (f'On the live board now (data): {layout} “{title}”' + (': ' + '; '.join(items) if items else '') +
            '. To add to it, start the reply with [board+]; a new topic gets a new [board …].\n')
