"""AppleScript from Python: run a script, and quote text for inside one."""
import subprocess

__all__ = ['osa', 'osa_quote']


def osa(script, *args, timeout=60):
    try: return subprocess.run(['osascript', '-e', script, *args], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except subprocess.TimeoutExpired: return ''   # a stuck Apple event must not hang the ask


def osa_quote(text):
    """Text for inside an AppleScript "…" literal: a model- or page-supplied name must never end the string and run code."""
    return str(text).replace('\\', '\\\\').replace('"', '\\"')
