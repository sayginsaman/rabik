"""The worker's stdout protocol to Rabik.app: one line per message, tagged by its first character.

  · note   ▸ step   ✓ answer   ! error/setup/feedback/improve   … streamed answer so far   i tip
  ? Allow card (tab-separated)   ◇ choices card   ⤴ hand-off   ⇢ move-to-agent control   ▣ work window
  @ x y pointer ring   ✎ drawing or memory receipt   ↺ replace/insert text   ⚙ key value   ▤ show an agent's card"""
import json
import os
import sys
import tempfile
import time
from brain import environ, paths

__all__ = ['say', 'emit']

on_stdout_closed = lambda: None   # rabik.py: stop this ask's workers once nobody reads its output


def say(tag, text):   # one line per message; an answer's own line breaks (lists, display math) travel as U+2028
    if tag not in ('✓', '…'): text = ' '.join(text.split())
    else:   # lines inside ``` fences keep their spacing (code, text diagrams)
        fence, lines = False, []
        for line in text.strip().splitlines():
            lines.append(line.rstrip() if fence and not line.lstrip().startswith('```') else ' '.join(line.split()))
            fence ^= line.lstrip().startswith('```')
        text = '\u2028'.join(lines)
    try:
        print(f'{tag} {text}', flush=True)
    except BrokenPipeError:
        sys.stdout = open(os.devnull, 'w')
        on_stdout_closed()


def emit(lines, directory=None):
    for line in lines[:1]:
        if line.startswith('▣ '):   # "click into it" next turn means this window, not whatever is in front
            try:
                with open(paths.WORKED, 'w') as f: json.dump({k: json.loads(line[2:]).get(k) for k in ('app', 'window')}, f)
            except (OSError, ValueError): pass
    ask = directory or environ.ask_dir()
    if ask and not environ.relay_owner_here():
        # Atomic, ordered events: the relay sees the window before its point, even for a fast chain.
        with tempfile.NamedTemporaryFile(mode='w', dir=ask, prefix='.hands-', delete=False) as f:
            f.write('\n'.join(lines)); name = f.name
        os.replace(name, os.path.join(ask, f'hands-{time.time_ns()}'))
    else:
        for line in lines: say(line[0], line[2:])
