"""Goals: up to five things the user is working toward ("my goal is to ship the beta"), on this Mac in goals.json. The daily
recap's one AI call says which of the day's work moved one forward; nothing else reads them except the MCP server."""
import json
import os
import re
import time
import uuid
from brain import paths, storage, wording

__all__ = ['GOALS_MOST', 'FOCUS_DAILY', 'FOCUS_GAP', 'goals_file', 'goals', 'goals_open', 'goal_add', 'goal_done', 'goal_drop', 'goals_command',
           'focus_nudge']


GOALS_MOST = 5
FOCUS_DAILY, FOCUS_GAP = 3, 45 * 60   # focus nudges: at most 3 a day, 45 minutes apart


def goals_file():
    return os.path.join(paths.DIR, 'goals.json')


def goals():
    try:
        with open(goals_file()) as f: data = json.load(f)
    except (OSError, ValueError): return []
    return [g for g in data if isinstance(g, dict) and isinstance(g.get('text'), str) and g.get('id')] if isinstance(data, list) else []


def goals_open():
    return [g for g in goals() if not g.get('done')]


def _save(rows):
    os.makedirs(paths.DIR, exist_ok=True); storage.private_json(goals_file(), rows)


def goal_add(text):
    text = ' '.join(str(text).split()).strip(' .')[:160]
    if not text: return 'Say the goal, like “my goal is to ship the beta by Friday”.'
    rows = goals()
    if any(wording.casekey(g['text']) == wording.casekey(text) and not g.get('done') for g in rows): return f'“{text}” is already a goal.'
    if len([g for g in rows if not g.get('done')]) >= GOALS_MOST: return f'You have {GOALS_MOST} goals. Finish or remove one first (Settings → General → Goals).'
    rows.append({'id': uuid.uuid4().hex[:8], 'text': text, 'added': time.time(), 'done': 0}); _save(rows)
    return f'Goal added: {text}. The daily recap will say when your day moves it forward.'


def _match(rows, words):
    want = wording._words(words) - wording.STOP - {'goal', 'goals', 'hedef', 'hedefi', 'hedefini'}
    scored = sorted(((len(want & wording._words(g['text'])), g) for g in rows), key=lambda s: s[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] and (len(scored) == 1 or scored[0][0] > scored[1][0]) else None


def goal_done(words='', ident=None, done=True):
    rows = goals()
    goal = next((g for g in rows if g['id'] == ident), None) if ident else _match([g for g in rows if bool(g.get('done')) != done], words)
    if not goal: return 'Which goal? Say a word from it.'
    goal['done'] = time.time() if done else 0; _save(rows)
    return f'Done: {goal["text"]}. Nice work.' if done else f'Back on your goals: {goal["text"]}.'


def goal_drop(ident):
    rows = goals(); kept = [g for g in rows if g['id'] != ident]
    if len(kept) != len(rows): _save(kept)
    return {'goals': kept}


def goals_command(args):
    """--goals list | add "<text>" | done <id> | undo <id> | drop <id> (Settings) — JSON."""
    action, rest = (args[0], ' '.join(args[1:])) if args else ('list', '')
    if action == 'add': note = goal_add(rest)
    elif action in ('done', 'undo') and re.fullmatch(r'[0-9a-f]{8}', rest): note = goal_done(ident=rest, done=action == 'done')
    elif action == 'drop' and re.fullmatch(r'[0-9a-f]{8}', rest): return goal_drop(rest)
    elif action == 'list': note = ''
    else: raise ValueError('Use --goals list | add "<text>" | done <id> | undo <id> | drop <id>')
    return {'goals': goals(), 'note': note}


def focus_nudge(where, minutes, now=None):
    """Rabik.app saw the user on a distracting site or app (YouTube, Reddit, …) for a while: one gentle line naming a goal they set,
    or {'skip': why}. Never without a goal, at most FOCUS_DAILY a day and FOCUS_GAP apart (focus-nudges.json counts them)."""
    now = now or time.time()
    open_goals = goals_open()
    if not open_goals: return {'skip': 'no goals'}
    where, minutes = ' '.join(str(where).split())[:40] or 'that', max(1, int(minutes))
    path, day = os.path.join(paths.DIR, 'focus-nudges.json'), time.strftime('%Y-%m-%d', time.localtime(now))
    try:
        with open(path) as f: state = json.load(f)
    except (OSError, ValueError): state = {}
    if not isinstance(state, dict) or state.get('day') != day: state = {'day': day, 'count': 0, 'last': 0}
    if state.get('count', 0) >= FOCUS_DAILY: return {'skip': 'daily limit'}
    if now - state.get('last', 0) < FOCUS_GAP: return {'skip': 'too soon'}
    goal = open_goals[state['count'] % len(open_goals)]['text']   # a different goal each time when there are several
    state.update(count=state['count'] + 1, last=now)
    os.makedirs(paths.DIR, exist_ok=True); storage.private_json(path, state)
    return {'text': f'{minutes} min on {where}. Your goal: {goal}. Back to it?', 'goal': goal}
