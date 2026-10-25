"""Anonymous usage and error counts (PostHog), off unless POSTHOG_KEY is set; failure reports scrubbed on this Mac."""
import base64
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from brain import paths, prefs

__all__ = ['POSTHOG_KEY', 'telemetry_enabled', 'install_id', 'posthog', 'ping', 'clean', 'report', 'report_error', 'exception_error',
           'install_exception_hooks', 'dictation_event', 'tool_kinds', 'ask_done']


# Anonymous counts, timings and error locations under a random install ID; never asks or screen content. Off in Settings → Privacy. Empty key = off.
POSTHOG_KEY = os.environ.get('RABIK_POSTHOG_KEY', '')   # your PostHog project's public capture token; empty = telemetry off


def telemetry_enabled():
    return bool(POSTHOG_KEY and prefs.pref('stats', True) and not os.environ.get('RABIK_DIR'))   # RABIK_DIR is the pure-test sandbox


def install_id():
    idf = os.path.join(paths.DIR, 'id')
    if not os.path.exists(idf):
        os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
        Path(idf).write_text(base64.b32encode(os.urandom(10)).decode())
    return Path(idf).read_text()


def posthog(event, props=None, stamp=()):
    """One anonymous event (a random ID, no person profile). stamp: (text, file) written once it is sent."""
    if not telemetry_enabled():
        return
    try:
        body = json.dumps({'api_key': POSTHOG_KEY, 'event': event, 'distinct_id': install_id(), 'properties': {'$process_person_profile': False, 'version': paths.APP_VERSION,
                                                                                                            'macos': platform.mac_ver()[0], 'client': prefs.client(), **(props or {})}})
        subprocess.Popen(['/bin/sh', '-c', 'curl -fsS -m 10 -H "Content-Type: application/json" -d "$1" https://us.i.posthog.com/i/v0/e/' + (' && printf %s "$2" > "$3"' if stamp else ''),
                          'rabik-ping', body, *stamp],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)   # cancellation cannot kill it or slow the answer
    except (OSError, ValueError):
        pass   # telemetry never breaks an ask


def ping():
    day, stamp = time.strftime('%Y-%m-%d'), os.path.join(paths.DIR, 'pinged')
    if not telemetry_enabled() or (os.path.exists(stamp) and Path(stamp).read_text() == day):
        return
    posthog('used', stamp=(day, stamp))


def clean(text):
    """Failure reports carry no emails, numbers, file paths, link queries, long tokens or text typed for the user."""
    t = str(text).replace(paths.ME, 'rabik').replace(paths.HOME, '~')
    t = re.sub(r'((?:--type|--hands type (?:"[^"]*"|\S+)|--web fill \d+)\s+)("(?:[^"\\]|\\.)*"|\'[^\']*\')', r'\1<text>', t)
    t = re.sub(r'((?:--hands|--web) type-after\s+(?:"(?:[^"\\]|\\.)*"|\'[^\']*\'|\S+)\s+)("(?:[^"\\]|\\.)*"|\'[^\']*\')', r'\1<text>', t)
    t = re.sub(r'(\b(?:keystroke|to)\s+|[{,]\s*\w+\s*:\s*)"(?:[^"\\]|\\.)*"', r'\1"<text>"', t)   # AppleScript typing and text set into apps
    t = re.sub(r'[\w.+-]+@[\w-]+\.[\w.]+', '<email>', t)
    t = re.sub(r'(https?://[^\s"\'?#]+)[?#][^\s"\']*', r'\1', t)
    t = re.sub(r'~/[^\s"\']+', '~/<path>', t)
    t = re.sub(r'(?<![:/])/(?:[^/\s"\']+/)+[^/\s"\']*', '<path>', t)
    t = re.sub(r'(?<![:/.\w])(?:[\w.-]+/)+[\w.-]+', '<path>', t)
    t = re.sub(r'\b[A-Za-z0-9_-]{24,}\b', '<secret>', t)
    return re.sub(r'\d[\d\s().-]{4,}\d', '<number>', t)[:300]


def report(task, reply, ran, secs, why):
    """Settings → Help improve Rabik (off until the user says yes): a task that failed goes to the maker, cleaned."""
    if POSTHOG_KEY and prefs.pref('improve', False) and os.environ.get('RABIK_LIVE') != '1':
        posthog('task_failed', {'task': clean(task), 'reply': clean(reply), 'steps': [clean(c) for c in list(ran)[:12]], 'why': why,
                                'secs': round(secs, 1), 'model': prefs.pref('model', 'haiku')})


def report_error(kind, **props):
    """Privacy-safe failures only: callers pass enums, indexes and code locations, never user text."""
    if telemetry_enabled():
        posthog('error', {'kind': kind, **props})


_BRAIN = os.path.dirname(os.path.abspath(__file__)) + os.sep


def _ours(tb):
    """A frame of Rabik's own code: the entry script or a brain/ module."""
    return tb.tb_frame.f_code.co_filename == paths.ME or tb.tb_frame.f_code.co_filename.startswith(_BRAIN)


def exception_error(exc_type, tb, value=None):
    ours = None   # the last Rabik line on the way down: a crash inside subprocess.py still says which call failed
    while tb and tb.tb_next:
        if _ours(tb): ours = tb
        tb = tb.tb_next
    if tb and _ours(tb): ours = tb
    frame = tb.tb_frame if tb else None
    errno = value.errno if isinstance(value, OSError) else None   # OSError's own field: never a custom attribute that could throw here
    report_error('exception', exception=getattr(exc_type, '__name__', 'Exception'),
                 file=os.path.basename(frame.f_code.co_filename) if frame else '',
                 line=tb.tb_lineno if tb else 0, function=frame.f_code.co_name if frame else '',
                 at_line=ours.tb_lineno if ours else 0, at_function=ours.tb_frame.f_code.co_name if ours else '',
                 **({'errno': errno} if isinstance(errno, int) else {}))


def install_exception_hooks():
    previous_sys, previous_thread = sys.excepthook, getattr(threading, 'excepthook', None)
    def system_hook(exc_type, value, tb):
        exception_error(exc_type, tb, value)
        previous_sys(exc_type, value, tb)
    def thread_hook(args):
        exception_error(args.exc_type, args.exc_traceback, args.exc_value)
        if previous_thread: previous_thread(args)
    sys.excepthook = system_hook
    if previous_thread: threading.excepthook = thread_hook


def dictation_event(mode, secs, cleanup, fallback, timed_out, insert):
    posthog('dictation', {'mode': mode if mode in ('verbatim', 'cleanup') else 'verbatim',
                          'secs': round(max(0, float(secs)), 3), 'cleanup_used': bool(cleanup),
                          'fell_back': bool(fallback), 'timed_out': bool(timed_out),
                          'insert': insert if insert in ('ok', 'no box', 'failed') else 'failed'})


def tool_kinds(commands):
    """Command classes only, never their arguments."""
    kinds = []
    for command in commands:
        helpers = re.findall(r'--(place|show|hands|web|draw|look|search|read|front|watch|pick|play|queue|type|window)\b', str(command))
        if helpers:
            found = helpers
        else:
            try: tokens = shlex.split(str(command).split('=>', 1)[0])
            except ValueError: tokens = []
            found = [os.path.basename(tokens[0])] if tokens else []
        for kind in found:
            if kind and kind not in kinds: kinds.append(kind)
    return kinds[:20]


def ask_done(row):
    if row.get('_telemetry_sent'):
        return
    status = row.get('status')
    status = 'ok' if status in ('completed', 'handed_off') else 'failed' if status in ('failed', 'crashed') else 'cancelled'
    steps = row.get('steps', 0)
    posthog('ask_done', {'path': row.get('path', 'instant' if row.get('model') == 'instant' else 'model'),
                         'model': row.get('model', 'unknown'), 'secs': round(max(0, float(row.get('secs', 0))), 1),
                         'steps': len(steps) if isinstance(steps, (list, tuple)) else max(0, int(steps or 0)),
                         'tools': tool_kinds(row.get('ran', [])), 'status': status,
                         'escalated': bool(row.get('escalated'))})
    row['_telemetry_sent'] = True
