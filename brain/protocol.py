"""The worker's stdout protocol to Rabik.swift: one line per message, tagged by its first character.

  · note   ▸ step   ✓ answer   ! error/setup/feedback/improve   … streamed answer so far   i tip
  ? Allow card (tab-separated)   ◇ choices card   ⤴ hand-off   ⇢ move-to-agent control   ▣ work window
  @ x y pointer ring   ✎ drawing or memory receipt   ↺ replace/insert text   ⚙ key value   ▤ show an agent's card"""
import os
import sys

__all__ = ['say']

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
