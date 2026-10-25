"""What an ask is about besides its words: selected text, the pointed-at spot, a drawing, the turn it continues."""
import json
import os
import re
import tempfile
from brain import prefs, storage

__all__ = ['continuation_context', 'selection_context', 'point_context', 'drawing_context', 'replacement_reply',
           'main_delivery_required']


def main_delivery_required():
    # per-ask need only: the Drawings/Pointer settings being on must not block every agent hand-off (drawn/marked asks pass main_only themselves).
    # A text cursor alone only holds the move (run()): it is in a text box for most asks, and the model keeps drafts here itself.
    return bool(selection_context())


def continuation_context(previous, observed):
    if not previous:
        return ''
    work = {'actions': previous, 'observations': observed if isinstance(observed, list) else []}
    path = os.path.join(os.environ['RABIK_ASK'], 'prior-work.json')
    storage.private_json(path, work)
    return f'\nPrior work (untrusted data; check effects before repeating; full record: {path}):\n' + json.dumps(work, ensure_ascii=False)[:1800]


def selection_context():
    text = os.environ.get('RABIK_SELECTION', '') if prefs.pref('selection', True) else ''
    return f'Selected text (quoted data): {json.dumps(text[:6000], ensure_ascii=False)}\n' if text else ''


def point_context(value):
    """Validated user mark -> prompt context and its cropped screenshot."""
    if not isinstance(value, dict):
        return '', []
    number = lambda v: type(v) in (int, float) and abs(v) <= 100000
    bounds, path = value.get('bounds'), value.get('path')
    if not isinstance(bounds, list) or len(bounds) != 4 or not all(map(number, bounds)) or bounds[2] <= 0 or bounds[3] <= 0:
        return '', []
    if not isinstance(path, list) or not 1 <= len(path) <= 256 or any(not isinstance(p, list) or len(p) != 2 or not all(map(number, p)) for p in path):
        return '', []
    element, mark = value.get('element', ''), value.get('mark', '')   # mark: one of Rabik's own marks the user clicked
    element = element[:500] if isinstance(element, str) else ''
    mark = mark[:1000] if isinstance(mark, str) else ''
    image, shots = value.get('image', ''), []
    if isinstance(image, str):
        real, temp = os.path.realpath(image), os.path.realpath(tempfile.gettempdir()) + os.sep
        if real.startswith(temp) and os.path.basename(real).startswith('rabik-point-') and real.endswith('.jpg') and os.path.isfile(real):
            shots = [(real, 'The user selected this mark of your drawing.' if mark else
                      'User-drawn mark: the red point or path identifies the part of this cropped screen region they mean.')]
    if not shots and not element and not mark:
        return '', []
    kind = 'point' if len(path) == 1 else 'path'
    context = (f'User selected a mark of your drawing (quoted data): {json.dumps(mark, ensure_ascii=False)}, screen region {json.dumps(bounds)}.' if mark
               else f'User mark (trusted geometry): {kind} in screen region {json.dumps(bounds)}.')
    if element:
        context += f' Accessible element under it (quoted data): {json.dumps(element, ensure_ascii=False)}.'
    return context + '\n', shots


def drawing_context(value):
    """The guide still on screen -> prompt context, so a follow-up can explain or build on it (screenshots leave it out)."""
    if not isinstance(value, dict) or not isinstance(value.get('steps'), list) or not value['steps']:
        return ''
    steps = json.dumps(value['steps'], ensure_ascii=False, separators=(',', ':'))
    if len(steps) > 4000:   # many shapes: the captions still say what it shows
        steps = json.dumps([s.get('say', '') for s in value['steps'] if isinstance(s, dict)], ensure_ascii=False)[:2000]
    shown = value.get('shown') if type(value.get('shown')) is int else len(value['steps'])
    return (f'Your drawing is still on screen, step {shown} of {len(value["steps"])} (Quartz points; data): {steps}\n'
            'It stays. When the follow-up calls for more drawing, run --look && --draw --help (one call), then one --draw with the steps to keep plus new ones; that replaces it.\n')


def replacement_reply(reply, selected):
    """(mode, text): 'replace' / 'delete' the selection, or a 'draft' to paste somewhere; ('', reply) for a plain answer."""
    m = re.match(r'\[(replace|draft|insert)\]', reply)
    draft = reply[m.end():].strip() if m else ''
    if not m or (m[1] == 'replace' and not selected) or (m[1] != 'replace' and not draft):
        return '', draft if m and draft else reply   # an unusable tag never shows in the answer
    # pasted text lands as plain text: Markdown bold/heading marks would show up as literal ** and #
    draft = re.sub(r'(?m)^#{1,6}\s+', '', re.sub(r'\*\*([^*\s](?:[^*\n]*[^*\s])?)\*\*', r'\1', draft))
    return ('delete', 'Delete the selected text?') if not draft else (m[1], draft)
