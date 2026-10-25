"""The small tip under an answer: how to teach Rabik after a miss, otherwise a general one at most every 6 hours."""
import os
import time
from pathlib import Path
from brain import environ, paths, prefs, protocol, wording

__all__ = ['TIPS', 'MISS', 'tip']


TIPS = ['Say "remember …" and Rabik keeps it as a rule.',
        'Say "when I say study mode, open …" to make your own instant command.',
        'Ask "where do I click to …" and a ring marks the spot.',
        'Tap the shortcut to type instead of talk.',
        'Sonnet gives better answers on hard tasks. Settings → Intelligence → Balanced uses it for real work.']


MISS = 'Saying the same thing more than once? Tell Rabik how you want it done. It remembers next time.'


def tip(reply, taught='', work=False):
    """One small tip under the answer ("i <tip>"). After a miss or a redo: how to teach it (the AI's own words if it gave some),
    every time; otherwise a general tip at most every 6 h. Off in Settings."""
    if not environ.in_box():
        return
    tips, miss = prefs.pref('tips', True), taught or wording.failed_action_reply(reply, work)
    if taught.startswith('Learned:') or tips and miss:
        return protocol.say('i', taught or MISS)
    stamp = os.path.join(paths.DIR, 'tip')
    if miss:
        return
    if not os.path.exists(stamp):   # never on the very first ask
        return Path(stamp).write_text('0')
    n = int(Path(stamp).read_text() or 0)
    if not tips or time.time() - os.path.getmtime(stamp) < 6 * 3600:
        return
    Path(stamp).write_text(str(n + 1))
    protocol.say('i', TIPS[n % len(TIPS)])
