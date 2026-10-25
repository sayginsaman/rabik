"""The ask in progress (TURN): its row in log.jsonl, checkpointed while it runs and finished once.

STOPPING is rebound when the ask is cancelled, so it is not in __all__ and never copied: read it as turn.STOPPING."""
import atexit
import os
import time
from brain import prefs, storage, telemetry

__all__ = ['TURN', 'checkpoint', 'begin_turn', 'end_turn', 'log_turn']

replayed = lambda: []   # rabik.py: the steps the last replayed shortcut ran (skills still lives there)


TURN = {}
STOPPING = False


def checkpoint(**values):
    """Append lightweight progress; read_rows folds it into the full request row."""
    if not TURN: return
    TURN.update(values)
    keys = ['id', 'pid', 'status', 'step_times', 'confirmed', 'model', 'escalated', 'escalate_why', 'attempt_usd', 'attempt_usage']
    if not TURN.get('_checkpointed'):
        keys += ['at', 'task', 'live', 'cursor']
        TURN['_checkpointed'] = True
    row = {k: TURN[k] for k in keys if k in TURN}
    row['secs'] = round(time.time() - TURN['_started'], 3)
    storage.append_log(row)


def begin_turn(task):
    global STOPPING
    STOPPING = False
    TURN.clear()
    started = time.time()
    TURN.update(id=f'{os.getpid()}-{time.time_ns()}', pid=os.getpid(), _started=started,
                at=time.strftime('%Y-%m-%d %H:%M:%S'), task=task, reply='', usd=0,
                steps=[], step_times=[], ran=[], status='running', live=os.environ.get('RABIK_LIVE') == '1',
                confirmed=not bool(os.environ.get('RABIK_COMMIT')), pics=0, cursor=os.environ.get('RABIK_CARET') == '1',
                model=prefs.main_model(), path='model', escalated=False, escalate_why=None, attempt_usd=[], attempt_usage=[])
    checkpoint()


def end_turn(status='cancelled', emit=True):
    if TURN and TURN.get('status') == 'running':
        now = time.monotonic()
        for step in TURN['step_times']:
            if step.get('status') == 'running':
                step.update(secs=round(now - step.pop('_start', now), 3), status=status)
        TURN['secs'] = round(time.time() - TURN['_started'], 1)
        checkpoint(status=status)
        if emit:
            telemetry.ask_done(TURN)
            if status == 'cancelled': telemetry.report_error('stopped')


atexit.register(end_turn)


def log_turn(task, reply, started, cost=0, steps=0, ran=(), pics=0, *, model=None, path='model', escalated=False, escalate_why=None, attempt_usd=None, attempt_usage=None):
    status = TURN.get('status', 'completed')
    model = model or TURN.get('model') or prefs.main_model()
    attempt_usd = list(attempt_usd) if attempt_usd is not None else ([] if model == 'instant' else [cost])
    row = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'task': task, 'reply': reply,
           'usd': round(cost, 5) if cost is not None else None, 'secs': round(time.time() - started, 1), 'steps': steps,
           'ran': list(ran) or replayed(), 'live': os.environ.get('RABIK_LIVE') == '1',
           'pics': pics, 'cursor': os.environ.get('RABIK_CARET') == '1', 'model': model, 'path': path, 'escalated': bool(escalated),
           'escalate_why': escalate_why if escalated else None, 'attempt_usd': attempt_usd,
           'attempt_usage': list(attempt_usage) if attempt_usage is not None else list(TURN.get('attempt_usage', []))}
    if TURN and TURN.get('task') == task:
        TURN.update(row, status='completed' if status == 'running' else status,
                    confirmed=not os.environ.get('RABIK_COMMIT') or os.path.exists(os.environ['RABIK_COMMIT']))
        storage.append_log({k: v for k, v in TURN.items() if not k.startswith('_')})
        telemetry.ask_done(TURN)
    else:
        storage.append_log(row)
