"""Drawings and pointing on screen (--draw, [point x y]): checking the model's shapes and sending them to the overlay."""
import json
import os
import re
import subprocess
import time
import uuid
from brain import hands, interaction, macos, paths, prefs, protocol

__all__ = ['draw_target', 'drawing', 'draw', 'guide_reply', 'point']


def draw_target():
    r = subprocess.run([paths.APP, '--draw-target'], capture_output=True, text=True, timeout=2)
    target = json.loads(r.stdout)
    if not isinstance(target, dict) or not target.get('windowID'): raise ValueError('No visible target window')
    return target


def drawing(data, mappings=None):
    """Validate the model boundary and convert actual screenshot pixels to global Quartz points."""
    def number(v):
        if type(v) not in (int, float) or not -100000 <= v <= 100000: raise ValueError('Invalid drawing coordinate')
        return v
    def vector(v, count):
        if not isinstance(v, list) or len(v) != count: raise ValueError('Invalid drawing coordinates')
        return [number(x) for x in v]
    if not isinstance(data, dict) or set(data) != {'steps'} or not isinstance(data['steps'], list) or not 1 <= len(data['steps']) <= 12:
        raise ValueError('Use {"steps":[...]} with 1-12 steps')
    steps = []
    for step in data['steps']:
        if not isinstance(step, dict) or set(step) - {'id','say','target','shapes','wait','hit','screen','timeout'}: raise ValueError('Invalid drawing step')
        out = {**step}
        for key, limit in [('id',80),('say',1000),('target',200)]:
            if key in step and (not isinstance(step[key], str) or not 1 <= len(step[key]) <= limit): raise ValueError('Invalid ' + key)
        if 'wait' in step and type(step['wait']) is not bool: raise ValueError('Invalid wait')
        timeout = number(step.get('timeout', 60))
        if not 5 <= timeout <= 120: raise ValueError('Timeout must be 5-120 seconds')
        out['timeout'] = timeout
        mapping = None
        if 'screen' in step:
            if type(step['screen']) is not int: raise ValueError('Invalid screen')
            mapping = (mappings or {}).get(str(step['screen']))
            if not mapping: raise ValueError('Read --look again before drawing in image pixels')
        def point(v):
            x, y = vector(v, 2)
            if mapping:
                fx, fy, fw, fh = mapping['frame']; pw, ph = mapping['pixels']
                if not 0 <= x <= pw or not 0 <= y <= ph: raise ValueError('Point outside screenshot')
                return [fx + x * fw / pw, fy + y * fh / ph]
            return [x,y]
        def rect(v):
            x,y,w,h = vector(v,4)
            if w <= 0 or h <= 0: raise ValueError('Drawing rectangle must have positive size')
            a,b = point([x,y]), point([x+w,y+h])
            return a + [b[0]-a[0], b[1]-a[1]]
        if 'hit' in step: out['hit'] = rect(step['hit'])
        shapes = step.get('shapes')
        if not isinstance(shapes,list) or not 1 <= len(shapes) <= 40: raise ValueError('Use 1-40 shapes per step')
        out['shapes'] = []
        for shape in shapes:
            if not isinstance(shape,dict) or set(shape) - {'kind','rect','at','points','text','color','size','fill'}: raise ValueError('Invalid shape')
            kind = shape.get('kind')
            if kind not in ('rect','circle','arrow','line','path','label','pointer','text'): raise ValueError('Invalid shape kind')
            fields = {'rect','fill'} if kind in ('rect','circle') else {'at','text','size'} if kind in ('label','text') else {'at'} if kind == 'pointer' else {'points'}
            if set(shape) - {'kind','color'} - fields: raise ValueError('Coordinates do not match shape kind')
            if shape.get('color','red') not in ('red','blue','green','yellow','white'): raise ValueError('Invalid color')
            if 'fill' in shape and type(shape['fill']) is not bool: raise ValueError('Fill must be true or false')
            value = {**shape}
            if kind in ('rect','circle'):
                if 'rect' in shape: value['rect'] = rect(shape['rect'])
                elif not step.get('target'): raise ValueError('Shape needs rect or AX target')
            elif kind == 'text':
                if 'at' in shape: value['at'] = point(shape['at'])
                if not isinstance(shape.get('text'),str) or not 1 <= len(shape['text']) <= 300: raise ValueError('Invalid text')
                if shape.get('size','m') not in ('s','m','l'): raise ValueError('Text size is s, m or l')
            elif kind in ('pointer','label'):
                if 'at' in shape: value['at'] = point(shape['at'])
                elif not step.get('target'): raise ValueError('Shape needs at or AX target')
            else:
                points = shape.get('points')
                if not isinstance(points,list) or not 2 <= len(points) <= (256 if kind == 'path' else 2): raise ValueError('Invalid path')
                value['points'] = [point(v) for v in points]
            if kind == 'label' and (not isinstance(shape.get('text'),str) or not 1 <= len(shape['text']) <= 120): raise ValueError('Invalid label')
            if kind == 'label' and shape.get('size','m') not in ('s','m','l'): raise ValueError('Label size is s, m or l')
            out['shapes'].append(value)
        if step.get('wait') and not step.get('target') and 'hit' not in step: raise ValueError('Waiting needs a target or hit rectangle')
        out.pop('screen', None); steps.append(out)
    teaching = all(not step.get('wait') and not step.get('target') and 'hit' not in step for step in steps)
    if teaching and any(not step.get('say') for step in steps): raise ValueError('Teaching steps need a visible say caption')
    return {'steps': steps, 'teaching': teaching}


def draw(data):
    if not prefs.pref('draw', True): raise ValueError('Screen drawings are off')
    if not interaction.wait_commit(): raise ValueError('Request cancelled before confirmation')
    ask = os.environ.get('RABIK_ASK')
    if not ask or os.environ.get('RABIK_AGENT'): raise ValueError('Drawing needs the main Rabik request')
    try:
        with open(os.path.join(ask, 'draw-screens.json')) as f: snapshot = json.load(f)
    except (OSError, ValueError): snapshot = {}
    if not snapshot.get('screens'): raise ValueError('Read --look before drawing so the guide matches the screen')
    value = drawing(data, snapshot.get('screens'))
    if any(s.get('target') for s in data['steps']):
        target = snapshot.get('target')
        if not isinstance(target, dict): raise ValueError('Read --look again before drawing')
        anchor = hands.hands_map(target=target)
        if not anchor: raise ValueError('The target window changed. Read --look again before drawing')
        value['target'] = {k: anchor[k] for k in ('pid','windowID','windowFrame')}
    else:
        value['target'] = snapshot.get('target') if any('screen' in s for s in data['steps']) else draw_target()
    value['state'] = paths.hands_state()
    receipt = os.path.join(ask, 'draw-result-' + uuid.uuid4().hex)
    value['receipt'] = receipt
    protocol.emit(['✎ ' + json.dumps(value, ensure_ascii=False)])
    try:
        for _ in range(50):
            if os.path.exists(receipt):
                with open(receipt) as f: result = f.read()
                if result != 'shown': raise ValueError(result)
                return f'Guide shown (step 1 of {len(value["steps"])}). Leave it running.'
            time.sleep(.1)
        raise ValueError('Drawing overlay did not respond')
    finally:
        if os.path.exists(receipt): os.unlink(receipt)


def guide_reply(observations, reply):
    return 'Done. Steps are on screen.' if any(
        not row.get('error') and str(row.get('result', '')).startswith('Guide shown (') for row in observations) else reply


def point(reply):
    """Experimental "show me where": the AI ends with [point N X Y] (screen N's picture, 1280 px wide).
    The overlay gets "@ <x> <y> answer" in screen points ("answer": a leader line and a held ring, unlike a click's spot); the user sees the reply without the tag."""
    m = re.search(r'\[point\b([^\]]*)\]', reply)
    if not m:
        return reply
    clean_reply = (reply[:m.start()] + reply[m.end():]).strip()
    try:
        n, x, y = map(int, m[1].split())
    except (TypeError, ValueError):
        return clean_reply
    scr = macos.screens()
    if not 1 <= n <= len(scr) or x < 0 or y < 0:
        return clean_reply
    screen = scr[n - 1]
    k = screen[3] / 1280
    if k <= 0 or x > 1280 or y > screen[4] / k:
        return clean_reply
    protocol.say('@', f'{round(screen[1] + x * k)} {round(screen[2] + y * k)} answer')
    return clean_reply
