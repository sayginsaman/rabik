"""Routines: requests the user scheduled, run by launchd jobs that call the helper's --routine."""
import fcntl
import json
import os
import plistlib
import re
import subprocess
import sys
import time
import uuid
from brain import environ, paths, prefs, prompts, storage

__all__ = ['ROUTINE_DAY_NAMES', 'ROUTINE_LATE', 'routine_days', 'routine_due', 'routines', 'routine_label', 'routine_job_path', 'routine_install',
           'routine_recap_sync', 'routine_repair', 'routine_add', 'routine_remove', 'routine_slot', 'routine_notify', 'routine_queue',
           'routine_wake', 'routine_fire', 'routine_pop', 'routine_command']


ROUTINE_DAY_NAMES = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')   # Python's weekday order


ROUTINE_LATE = {'skip': 15 * 60, '2h': 2 * 3600, 'always': float('inf')}   # Settings → a one-time task the Mac slept through


def routine_days(days):
    """daily | weekdays | weekends | "mon,thu" -> the weekdays it runs on (0 = Monday), or None when it is not a valid choice."""
    named = {'daily': set(range(7)), 'weekdays': set(range(5)), 'weekends': {5, 6}}
    if days in named: return named[days]
    parts = str(days).split(',') if isinstance(days, str) else []
    if not parts or any(p not in ROUTINE_DAY_NAMES for p in parts) or len(set(parts)) != len(parts): return None
    return {ROUTINE_DAY_NAMES.index(p) for p in parts}


def routine_due(row):
    """A one-time routine's moment, in seconds since the epoch."""
    year, month, day = map(int, row['date'].split('-')); hour, minute = map(int, row['at'].split(':'))
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


def routines():
    try:
        with open(os.path.join(paths.DIR, 'routines.json')) as f: rows = json.load(f)
        if not isinstance(rows, list): return []
        valid = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not re.fullmatch(r'[a-f0-9]{12}', row['id']) or not isinstance(row.get('ask'), str) or not row['ask']:
                continue
            if type(row.get('created')) not in (int, float) or row.get('mode', 'cheapest') not in ('cheapest', 'balanced', 'capable'):
                continue
            if row.get('kind') == 'interval':
                if type(row.get('every')) is not int or row['every'] < 60 or row['every'] % 60: continue
            elif row.get('kind') == 'time':
                if not isinstance(row.get('at'), str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', row['at']) or routine_days(row.get('days')) is None: continue
            elif row.get('kind') == 'once':
                if not isinstance(row.get('at'), str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', row['at']) or not isinstance(row.get('date'), str) \
                        or not re.fullmatch(r'20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])', row['date']): continue
            else:
                continue
            valid.append(row)
        return valid
    except (OSError, ValueError):
        return []


def routine_label(row):
    """How Settings and the AI say it: "Mondays and Thursdays at 9:00 AM", "Once on Fri, Oct 30 at 8:00 PM", "Every 30 minutes"."""
    suffix = ' · runs without asking' if row.get('unattended') else ''
    if row['kind'] == 'interval':
        seconds = row['every']
        amount, unit = (seconds // 3600, 'hour') if seconds % 3600 == 0 else (seconds // 60, 'minute')
        return f"Every {amount if amount != 1 else ''} {unit}{'s' if amount != 1 else ''}".replace('  ', ' ') + suffix
    hour, minute = map(int, row['at'].split(':'))
    clock = f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
    if row['kind'] == 'once':
        return 'Once on ' + time.strftime('%a, %b %-d', time.localtime(routine_due(row))) + ' at ' + clock + suffix
    named = {'daily': 'Every day', 'weekdays': 'Weekdays', 'weekends': 'Weekends'}
    if row['days'] in named: return named[row['days']] + ' at ' + clock + suffix
    days = [('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')[d] + 's' for d in sorted(routine_days(row['days']))]
    return (days[0] if len(days) == 1 else ', '.join(days[:-1]) + ' and ' + days[-1]) + ' at ' + clock + suffix


def routine_job_path(identifier):
    root = os.path.join(paths.DIR, 'launchagents') if environ.sandbox_dir() else os.path.join(paths.HOME, 'Library', 'LaunchAgents')
    return os.path.join(root, f'com.rabik.routine.{identifier}.plist')


def routine_install(row):
    path = routine_job_path(row['id']); os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    job = {'Label': f"com.rabik.routine.{row['id']}", 'ProgramArguments': ['/bin/sh', paths.ME, '--routine-fire', row['id']],   # rabik.py picks the Python inside Rabik.app
           'ProcessType': 'Background', 'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'}
    if row['kind'] == 'interval':
        job['StartInterval'] = row['every']
    elif row['kind'] == 'once':   # launchd has no year: routine_slot checks it, and the routine goes once it starts
        _, month, day = map(int, row['date'].split('-')); hour, minute = map(int, row['at'].split(':'))
        job['StartCalendarInterval'] = {'Month': month, 'Day': day, 'Hour': hour, 'Minute': minute}
    else:
        hour, minute = map(int, row['at'].split(':'))
        values = {'Hour': hour, 'Minute': minute}
        days = routine_days(row['days'])   # launchd counts Sunday as 0, Monday as 1
        job['StartCalendarInterval'] = values if len(days) == 7 else [{**values, 'Weekday': (day + 1) % 7} for day in sorted(days)]
    with open(path + '.tmp', 'wb') as f: plistlib.dump(job, f)
    os.chmod(path + '.tmp', 0o600); os.replace(path + '.tmp', path)
    if not environ.sandbox_dir():
        target = f'gui/{os.getuid()}'
        subprocess.run(['/bin/launchctl', 'bootout', target, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        loaded = subprocess.run(['/bin/launchctl', 'bootstrap', target, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if loaded.returncode:
            time.sleep(.2)
            loaded = subprocess.run(['/bin/launchctl', 'bootstrap', target, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if loaded.returncode:
            try: os.remove(path)
            except FileNotFoundError: pass
            raise OSError('Could not start the routine. Try again.')


def routine_recap_sync():
    """The daily recap's launchd job follows Settings: on, a daily job at recapAt that wakes the app; off, no job."""
    at, path = str(prefs.pref('recapAt', '21:00')), routine_job_path('recap')
    if prefs.pref('recap', True) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', at):
        try:
            with open(path, 'rb') as f:
                job = plistlib.load(f)
                if job.get('StartCalendarInterval') == {'Hour': int(at[:2]), 'Minute': int(at[3:])} and job.get('ProgramArguments', [])[:1] == ['/bin/sh']: return True
        except (OSError, ValueError, AttributeError): pass
        routine_install({'id': 'recap', 'kind': 'time', 'at': at, 'days': 'daily'})
        return True
    if os.path.exists(path):
        if not environ.sandbox_dir():
            subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(path)
    return False


def routine_repair():
    """Rewrite jobs written the old way: weekday jobs with Tuesday-Saturday values, and jobs that named a Python of their own
    instead of starting rabik.py (which picks the one inside Rabik.app); keep the daily recap's job in step with Settings. A one-time
    routine whose moment passed while the Mac was off runs now or is reported missed, by Settings."""
    try: routine_recap_sync()
    except (OSError, ValueError): pass
    for row in routines():
        if row['kind'] == 'once' and not row.get('lastSlot') and routine_due(row) <= time.time():
            routine_fire(row['id']); continue
        try:
            with open(routine_job_path(row['id']), 'rb') as f: job = plistlib.load(f)
            days = [value.get('Weekday') for value in job.get('StartCalendarInterval', [])]
            started = job.get('ProgramArguments', [])
        except (OSError, ValueError, TypeError, AttributeError):
            days, started = [], []
        if (row.get('kind') == 'time' and row.get('days') == 'weekdays' and days != list(range(1, 6))) or started[:1] != ['/bin/sh']:
            try: routine_install(row)
            except (OSError, ValueError, KeyError, TypeError): pass


def routine_add(kind, when, ask, mode='cheapest', now=None, days='daily', date=None, unattended=False):
    """unattended: the user agreed, when it was set up, that it acts without asking then (the gate showed them the card)."""
    ask, mode = ' '.join(str(ask).split())[:1000], str(mode).lower()
    if not ask: raise ValueError('The routine needs an ask.')
    if mode not in ('cheapest', 'balanced', 'capable'): raise ValueError('Intelligence must be cheapest, balanced or capable.')
    now = time.time() if now is None else now
    row = {'id': uuid.uuid4().hex[:12], 'kind': kind, 'ask': ask, 'mode': mode, 'created': now}
    if unattended: row['unattended'] = True
    if kind in ('time', 'once'):
        match = re.fullmatch(r'([01]\d|2[0-3]):([0-5]\d)', str(when))
        if not match: raise ValueError('Time must be HH:MM.')
        row['at'] = when
    if kind == 'time':
        days = ','.join(d for d in ROUTINE_DAY_NAMES if d in str(days).split(',')) if routine_days(days) is not None and ',' in str(days) else days
        if routine_days(days) is None: raise ValueError('Days must be daily, weekdays, weekends or days like mon,thu.')
        row['days'] = days
    elif kind == 'once':
        today = time.localtime(now)
        if date in ('today', 'tomorrow'):
            date = time.strftime('%Y-%m-%d', time.localtime(time.mktime((today.tm_year, today.tm_mon, today.tm_mday + (date == 'tomorrow'), 12, 0, 0, 0, 0, -1))))
        if not re.fullmatch(r'20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])', str(date)): raise ValueError('Date must be YYYY-MM-DD, today or tomorrow.')
        row['date'] = date
        due = routine_due(row)
        if time.strftime('%Y-%m-%d', time.localtime(due)) != date: raise ValueError('That date does not exist.')
        if due <= now + 30: raise ValueError('That time has already passed. Pick a later time.')
        if due > now + 366 * 86400: raise ValueError('Pick a time within a year.')
    elif kind == 'interval':
        seconds = int(when)
        if seconds < 60 or seconds % 60: raise ValueError('Intervals must be whole minutes, at least 60 seconds.')
        row['every'] = seconds
    else:
        raise ValueError('Use time, once or interval.')
    row['label'] = routine_label(row)   # Settings shows it as is
    os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
    lock = open(os.path.join(paths.DIR, 'routines.lock'), 'a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = routines(); rows.append(row); storage.private_json(os.path.join(paths.DIR, 'routines.json'), rows)
        try: routine_install(row)
        except Exception:
            storage.private_json(os.path.join(paths.DIR, 'routines.json'), rows[:-1])
            raise
    finally:
        lock.close()
    return row


def routine_remove(identifier):
    if not re.fullmatch(r'[a-f0-9]{12}', identifier): return False
    os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
    lock = open(os.path.join(paths.DIR, 'routines.lock'), 'a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = routines(); kept = [row for row in rows if row.get('id') != identifier]
        if len(rows) == len(kept): return False
        storage.private_json(os.path.join(paths.DIR, 'routines.json'), kept)
    finally:
        lock.close()
    path = routine_job_path(identifier)
    if not environ.sandbox_dir():
        subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try: os.remove(path)
    except FileNotFoundError: pass
    return True


def routine_slot(row, now=None):
    now = time.time() if now is None else now
    if row['kind'] == 'interval':
        slot = int((now - row['created']) // row['every'])
        return str(slot) if slot >= 1 else None
    if row['kind'] == 'once':   # due and not too late (Settings → what to do when the Mac slept through it)
        due = routine_due(row)
        late = ROUTINE_LATE.get(str(prefs.pref('routineLate', 'skip')), ROUTINE_LATE['skip'])
        return row['date'] + '@' + row['at'] if due <= now + 60 and now - due <= late else None
    local = time.localtime(now)
    hour, minute = map(int, row['at'].split(':'))
    due = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, minute, 0, 0, 0, -1))
    if due > now:
        due = time.mktime((local.tm_year, local.tm_mon, local.tm_mday - 1, hour, minute, 0, 0, 0, -1))
    scheduled = time.localtime(due)
    if scheduled.tm_wday not in routine_days(row['days']): return None
    if due < row['created'] or now - due > 15 * 60: return None
    return time.strftime('%Y-%m-%d@', scheduled) + row['at']


def routine_fire(identifier, now=None):
    if prefs.pref('paused', False): return False
    os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
    if identifier == 'recap':   # the daily recap: the app makes it (recap_due decides), no agent
        if not prefs.pref('recap', True): return False
        routine_queue('recap'); routine_wake(); return True
    if not re.fullmatch(r'[a-f0-9]{12}', identifier): return False
    lock = open(os.path.join(paths.DIR, 'routines.lock'), 'a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = routines(); row = next((r for r in rows if r.get('id') == identifier), None)
        slot = routine_slot(row, now) if row else None
        if row and row['kind'] == 'once' and not slot and not row.get('lastSlot') and routine_due(row) <= (time.time() if now is None else now):
            missed = row   # the Mac slept or was off through it, longer than Settings allows: say so, never run it late
        elif not slot or row.get('lastSlot') == slot: return False
        else: missed = None
        if missed:
            lock.close()
            routine_remove(identifier)
            routine_notify(f"Missed: {missed['ask'][:120]} (due {missed['label'] if missed.get('label') else missed['at']}). Your Mac was asleep.")
            return False
        row['lastSlot'], row['lastAt'] = slot, time.time() if now is None else now
        storage.private_json(os.path.join(paths.DIR, 'routines.json'), rows)
        routine_queue(identifier)
    finally:
        lock.close()
    routine_wake()
    return True


def routine_notify(text):
    if environ.sandbox_dir(): return
    subprocess.run(['/usr/bin/osascript', '-e', 'on run argv\ndisplay notification (item 1 of argv) with title "Rabik"\nend run', text],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def routine_queue(identifier):
    """One due job for the app: a routine's ID, or "recap"."""
    fd = os.open(os.path.join(paths.DIR, 'routine-queue.jsonl'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.write(json.dumps({'id': identifier}) + '\n')


def routine_wake():
    """The app reads the queue now: its login job is kicked, or, with no job and no app running, the app opens in the background."""
    if environ.sandbox_dir(): return
    wake = subprocess.run(['/bin/launchctl', 'kickstart', f'gui/{os.getuid()}/com.rabik.app'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wake.returncode and subprocess.run(['/usr/bin/pgrep', '-f', paths.APP], stdout=subprocess.DEVNULL).returncode:
        bundle = paths.APP.partition('/Contents/MacOS/')[0]
        if bundle.endswith('.app'): subprocess.Popen(['/usr/bin/open', '-gj', bundle], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def routine_pop():
    routine_repair()
    path = os.path.join(paths.DIR, 'routine-queue.jsonl'); os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        ids = []
        lines = f.readlines()
        for line in lines:
            try: row = json.loads(line)
            except ValueError: continue
            if isinstance(row, dict): ids.append(row.get('id'))
        if lines: f.seek(0); f.truncate()
    return [identifier for identifier in ids if isinstance(identifier, str)]


def routine_command(args):
    """--routine add time|once|interval … [mode] [--unattended] | list | remove ID | --help."""
    unattended = '--unattended' in args
    args = [a for a in args if a != '--unattended']
    if args in ([], ['--help'], ['help']): return prompts.ROUTINE_HELP
    if args == ['list']:
        rows = routines()
        return '\n'.join(f"{row['id']} · {routine_label(row)} · {row['ask']} · {row.get('mode', 'cheapest').title()}" for row in rows) or 'No scheduled routines.'
    if len(args) in (5, 6) and args[:2] == ['add', 'time']:
        days = args[3].lower().replace(' ', '')
        days = ','.join(d[:3] for d in days.split(',')) if days not in ('daily', 'weekdays', 'weekends') else days   # "monday,thursday" too
        row = routine_add('time', args[2], args[4], args[5] if len(args) > 5 else 'cheapest', days=days, unattended=unattended)
        return f"Scheduled {routine_label(row)}: {row['ask']}"
    if len(args) in (5, 6) and args[:2] == ['add', 'once']:
        row = routine_add('once', args[3], args[4], args[5] if len(args) > 5 else 'cheapest', date=args[2].lower(), unattended=unattended)
        return f"Scheduled {routine_label(row)}: {row['ask']}"
    if len(args) in (4, 5) and args[:2] == ['add', 'interval']:
        row = routine_add('interval', args[2], args[3], args[4] if len(args) > 4 else 'cheapest', unattended=unattended)
        return f"Scheduled {routine_label(row)}: {row['ask']}"
    if len(args) == 2 and args[0] == 'remove':
        return 'Removed the routine.' if routine_remove(args[1]) else 'That routine no longer exists.'
    raise ValueError(prompts.ROUTINE_HELP)
