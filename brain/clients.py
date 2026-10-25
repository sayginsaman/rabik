"""The AI client processes an ask starts (Claude Code, Devin, Pi): stopping one with everything it started."""
import os
import signal
import time

__all__ = ['stop_claude']


def stop_claude(p):
    try:
        os.killpg(p.pid, signal.SIGTERM)   # hands releases a held mouse button before the hard stop
        time.sleep(.05)
        os.killpg(p.pid, signal.SIGKILL)   # includes running tools and permission hooks
    except OSError:   # already gone, or its group is out of reach (EPERM): nothing left to stop
        pass
