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
from brain import paths, prefs, storage

__all__ = ['routines', 'routine_label', 'routine_job_path', 'routine_install', 'routine_repair', 'routine_add', 'routine_remove',
           'routine_slot', 'routine_fire', 'routine_pop', 'routine_command']


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
                if not isinstance(row.get('at'), str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', row['at']) or row.get('days') not in ('daily', 'weekdays'): continue
            else:
                continue
            valid.append(row)
        return valid
    except (OSError, ValueError):
        return []


def routine_label(row):
    if row['kind'] == 'interval':
        seconds = row['every']
        amount, unit = (seconds // 3600, 'hour') if seconds % 3600 == 0 else (seconds // 60, 'minute')
        return f"Every {amount if amount != 1 else ''} {unit}{'s' if amount != 1 else ''}".replace('  ', ' ')
    hour, minute = map(int, row['at'].split(':'))
    clock = f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
    return ('Weekdays' if row['days'] == 'weekdays' else 'Every day') + ' at ' + clock


def routine_job_path(identifier):
    root = os.path.join(paths.DIR, 'launchagents') if os.environ.get('RABIK_DIR') else os.path.join(paths.HOME, 'Library', 'LaunchAgents')
    return os.path.join(root, f'com.rabik.routine.{identifier}.plist')


def routine_install(row):
    path = routine_job_path(row['id']); os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    job = {'Label': f"com.rabik.routine.{row['id']}", 'ProgramArguments': [sys.executable, paths.ME, '--routine-fire', row['id']],
           'ProcessType': 'Background', 'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'}
    if row['kind'] == 'interval':
        job['StartInterval'] = row['every']
    else:
        hour, minute = map(int, row['at'].split(':'))
        values = {'Hour': hour, 'Minute': minute}
        job['StartCalendarInterval'] = [{**values, 'Weekday': day} for day in range(1, 6)] if row['days'] == 'weekdays' else values
    with open(path + '.tmp', 'wb') as f: plistlib.dump(job, f)
    os.chmod(path + '.tmp', 0o600); os.replace(path + '.tmp', path)
    if not os.environ.get('RABIK_DIR'):
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


def routine_repair():
    """Replace weekday jobs written with the old Tuesday-Saturday values."""
    for row in routines():
        if row.get('kind') != 'time' or row.get('days') != 'weekdays': continue
        try:
            with open(routine_job_path(row['id']), 'rb') as f: job = plistlib.load(f)
            days = [value.get('Weekday') for value in job.get('StartCalendarInterval', [])]
        except (OSError, ValueError, TypeError, AttributeError):
            days = []
        if days != list(range(1, 6)):
            try: routine_install(row)
            except (OSError, ValueError, KeyError, TypeError): pass


def routine_add(kind, when, ask, mode='cheapest', now=None, days='daily'):
    ask, mode = ' '.join(str(ask).split())[:1000], str(mode).lower()
    if not ask: raise ValueError('The routine needs an ask.')
    if mode not in ('cheapest', 'balanced', 'capable'): raise ValueError('Intelligence must be cheapest, balanced or capable.')
    row = {'id': uuid.uuid4().hex[:12], 'kind': kind, 'ask': ask, 'mode': mode, 'created': time.time() if now is None else now}
    if kind == 'time':
        match = re.fullmatch(r'([01]\d|2[0-3]):([0-5]\d)', str(when))
        if not match: raise ValueError('Time must be HH:MM.')
        if days not in ('daily', 'weekdays'): raise ValueError('Days must be daily or weekdays.')
        row.update(at=when, days=days)
    elif kind == 'interval':
        seconds = int(when)
        if seconds < 60 or seconds % 60: raise ValueError('Intervals must be whole minutes, at least 60 seconds.')
        row['every'] = seconds
    else:
        raise ValueError('Use time or interval.')
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
    if not os.environ.get('RABIK_DIR'):
        subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try: os.remove(path)
    except FileNotFoundError: pass
    return True


def routine_slot(row, now=None):
    now = time.time() if now is None else now
    if row['kind'] == 'interval':
        slot = int((now - row['created']) // row['every'])
        return str(slot) if slot >= 1 else None
    local = time.localtime(now)
    hour, minute = map(int, row['at'].split(':'))
    due = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, minute, 0, 0, 0, -1))
    if due > now:
        due = time.mktime((local.tm_year, local.tm_mon, local.tm_mday - 1, hour, minute, 0, 0, 0, -1))
    scheduled = time.localtime(due)
    if row['days'] == 'weekdays' and scheduled.tm_wday >= 5: return None
    if due < row['created'] or now - due > 15 * 60: return None
    return time.strftime('%Y-%m-%d@', scheduled) + row['at']


def routine_fire(identifier, now=None):
    if not re.fullmatch(r'[a-f0-9]{12}', identifier): return False
    if prefs.pref('paused', False): return False
    os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
    lock = open(os.path.join(paths.DIR, 'routines.lock'), 'a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = routines(); row = next((r for r in rows if r.get('id') == identifier), None)
        slot = routine_slot(row, now) if row else None
        if not slot or row.get('lastSlot') == slot: return False
        row['lastSlot'], row['lastAt'] = slot, time.time() if now is None else now
        storage.private_json(os.path.join(paths.DIR, 'routines.json'), rows)
        queue = os.path.join(paths.DIR, 'routine-queue.jsonl')
        fd = os.open(queue, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a') as f:
            fcntl.flock(f, fcntl.LOCK_EX); f.write(json.dumps({'id': identifier}) + '\n')
    finally:
        lock.close()
    if not os.environ.get('RABIK_DIR'):
        wake = subprocess.run(['/bin/launchctl', 'kickstart', f'gui/{os.getuid()}/com.rabik.app'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wake.returncode and subprocess.run(['/usr/bin/pgrep', '-f', paths.APP], stdout=subprocess.DEVNULL).returncode:
            bundle = paths.APP.partition('/Contents/MacOS/')[0]
            if bundle.endswith('.app'): subprocess.Popen(['/usr/bin/open', '-gj', bundle], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


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
    if args == ['list']:
        rows = routines()
        return '\n'.join(f"{row['id']} · {routine_label(row)} · {row['ask']} · {row.get('mode', 'cheapest').title()}" for row in rows) or 'No scheduled routines.'
    if len(args) in (5, 6) and args[:2] == ['add', 'time'] and args[3] in ('daily', 'weekdays'):
        row = routine_add('time', args[2], args[4], args[5] if len(args) > 5 else 'cheapest', days=args[3])
        return f"Scheduled {routine_label(row)}: {row['ask']}"
    if len(args) in (4, 5) and args[:2] == ['add', 'interval']:
        row = routine_add('interval', args[2], args[3], args[4] if len(args) > 4 else 'cheapest')
        return f"Scheduled {routine_label(row)}: {row['ask']}"
    if len(args) == 2 and args[0] == 'remove':
        return 'Removed the routine.' if routine_remove(args[1]) else 'That routine no longer exists.'
    raise ValueError('Use: --routine add time HH:MM daily|weekdays "ask" [mode], add interval seconds "ask" [mode], list, or remove ID.')
