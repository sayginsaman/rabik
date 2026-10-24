#!/usr/bin/env python3
"""Run Atticus task evals against a fake Mac. --dry uses scripted Claude; --live uses real claude -p."""
import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest.mock as mock
from pathlib import Path
from tests.evals import fake_mac

ROOT = Path(__file__).resolve().parents[2]
EVALS = Path(__file__).resolve().parent


def _import_atticus(repo):
    repo = Path(repo).resolve()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    for mod in list(sys.modules):
        if mod == 'atticus' or mod.startswith('atticus.'):
            del sys.modules[mod]
    import atticus  # noqa: F401

    return sys.modules['atticus']


def _fake_app_script(path, atticus_py):
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{atticus_py}" "$@"\n')
    path.chmod(0o755)


def _write_fake_osascript(bin_dir):
    """Headless answers for relay pick / Allow dialogs (child --pick uses the same ATTICUS_ASK relay)."""
    script = bin_dir / 'osascript'
    script.write_text(r'''#!/bin/sh
if [ "$1" = "-e" ]; then
  case "$2" in
    *choose\ from\ list*) echo "$4"; exit 0 ;;
    *display\ dialog*) echo "Allow"; exit 0 ;;
  esac
fi
exec /usr/bin/osascript "$@"
''')
    script.chmod(0o755)


def _auto_allow(directory, stop):
    import atticus
    q = Path(atticus.question_path(directory))
    while not stop.is_set():
        if q.exists():
            try:
                j = json.loads(q.read_text())
            except (OSError, ValueError):
                j = {}
            q.unlink(missing_ok=True)
            a = Path(atticus.question_answer_path(directory, j))
            if 'pick' in j:
                a.write_text('1')
            else:
                a.write_text('y')
        time.sleep(0.05)


def _text_tool_pat():
    return r'--web read|--hands see|--hands read|--window\b|--read '


def _write_fake_claude(bin_dir, scenario, me):
    script = bin_dir / 'claude'
    lines = scenario.get('dry_bash', [])
    expect = scenario.get('expect', {})
    result = scenario.get('dry_result') or (
        ' '.join(expect['answer_contains']) if expect.get('answer_contains') else 'Done.')
    chunks = []
    tid = 0
    for cmd in lines:
        tid += 1
        use_id = f'toolu_{tid:03d}'
        chunks.append(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'text', 'text': 'Working.'},
            {'type': 'tool_use', 'id': use_id, 'name': 'Bash', 'input': {'command': cmd.replace('$ATTICUS_ME', me)}},
        ]}}))
        chunks.append(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': use_id, 'content': 'ok'},
        ]}}))
    chunks.append(json.dumps({'type': 'result', 'result': result, 'total_cost_usd': 0.001, 'is_error': False}))
    script.write_text(f'''#!{sys.executable}
import json, os, subprocess, sys
lines = {chunks!r}
for line in lines:
    j = json.loads(line)
    if j.get("type") == "assistant":
        for b in j["message"]["content"]:
            if b.get("type") == "tool_use" and b.get("name") == "Bash":
                cmd = b["input"]["command"]
                if "--pick" not in cmd:
                    subprocess.run(cmd, shell=True, env=os.environ)
    print(line, flush=True)
''')
    script.chmod(0o755)


def _tool_sequence(ran):
    return '\n'.join(ran or [])


def score(scenario, ran, state, metrics, clarify_count=0, live=False, reply=''):
    expect = {**scenario.get('expect', {}), **(scenario.get('live_expect', {}) if live else {})}
    ok = True
    notes = []
    effects = state.get('effects', [])
    if expect.get('answer_contains'):
        body = reply or ''
        missing = [s for s in expect['answer_contains'] if s.lower() not in body.lower()]
        if missing:
            ok = False
            notes.append(f'reply missing: {missing}')
    if expect.get('effects'):
        missing = [e for e in expect['effects'] if e not in effects]
        if missing:
            ok = False
            notes.append(f'missing effects: {missing}')
    for page, wanted in expect.get('control_values', {}).items():
        values = {c.get('label'): c.get('value', '') for c in state.get('pages', {}).get(page, {}).get('controls', [])}
        wrong = {label: value for label, value in wanted.items() if values.get(label) != value}
        if wrong:
            ok = False
            notes.append(f'wrong control values on {page}: {wrong}')
    for bad in expect.get('forbid_effects', []):
        if bad in effects:
            ok = False
            notes.append(f'forbidden effect: {bad}')
    seq = _tool_sequence(ran)
    for pat in expect.get('tool_patterns', []):
        if not re.search(pat, seq, re.I):
            ok = False
            notes.append(f'missing tool pattern: {pat}')
    for pat in expect.get('forbid_tool_patterns', []):
        if re.search(pat, seq, re.I):
            ok = False
            notes.append(f'forbidden tool: {pat}')
    if expect.get('text_before_look'):
        ran_list = ran or []
        look_i = next((i for i, c in enumerate(ran_list) if '--look' in c or 'screencapture' in c), len(ran_list))
        text_i = next((i for i, c in enumerate(ran_list) if re.search(_text_tool_pat(), c, re.I)), len(ran_list))
        upfront = metrics.get('front_text_chars', 0) >= 160
        if look_i < len(ran_list) and text_i > look_i and not upfront:
            ok = False
            notes.append('used look before text tools')
    max_q = expect.get('max_clarify_questions')
    if max_q is not None:
        if 'pick' in seq.lower() and clarify_count == 0:
            clarify_count = 1
        if clarify_count > max_q:
            ok = False
            notes.append(f'too many clarify questions ({clarify_count})')
    if metrics.get('risky_without_allow', 0):
        ok = False
        notes.append(f'risky without allow: {metrics["risky_without_allow"]}')
    return {
        'id': scenario['id'],
        'ok': ok,
        'round_trips': metrics.get('round_trips', len(ran or [])),
        'seconds': round(metrics.get('seconds', 0), 2),
        'usd': metrics.get('usd', 0),
        'notes': '; '.join(notes) or 'ok',
        'effects': effects,
        'cmds': ran or [],
    }


def run_scenario(scenario, repo, live=False):
    from tests.evals.scenarios import initial_state

    repo = Path(repo).resolve()
    atticus_path = repo / 'atticus.py'
    if not atticus_path.is_file():
        raise FileNotFoundError(atticus_path)

    scratch = tempfile.TemporaryDirectory(prefix='atticus-eval-')  # kept until run_scenario returns
    state_path = os.path.join(scratch.name, 'state.json')
    log_path = os.path.join(scratch.name, 'tool-log.jsonl')
    fake_app = Path(scratch.name) / 'fake-atticus-app'
    _fake_app_script(fake_app, atticus_path)
    state = initial_state(scenario)
    with open(state_path, 'w') as f:
        json.dump(state, f)

    bin_dir = Path(scratch.name)
    path_prefix = str(bin_dir) + os.pathsep + os.environ.get('PATH', '')
    fake_claude = str(bin_dir / 'claude')
    _write_fake_osascript(bin_dir)
    if not live:
        _write_fake_claude(bin_dir, scenario, str(atticus_path))
    environment = {
        'ATTICUS_DIR': scratch.name,
        'ATTICUS_APP': str(fake_app),
        'ATTICUS_FRONT': scenario.get('front_app', 'Fixture'),
        'ATTICUS_COMMIT': os.path.join(scratch.name, 'commit'),
        'ATTICUS_UI': '0',
        'ATTICUS_EVAL_STATE': state_path,
        'ATTICUS_EVAL_LOG': log_path,
        'ATTICUS_EVAL_ME': str(atticus_path),
        'PATH': path_prefix,
        'PYTHONPATH': str(EVALS) + os.pathsep + os.environ.get('PYTHONPATH', ''),
    }
    if not live:
        environment['ATTICUS_CLAUDE'] = fake_claude
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.dict(os.environ, environment))
    stack.enter_context(mock.patch.dict(sys.modules))  # put back the atticus module other tests patch
    for key in ('ATTICUS_ASK', 'ATTICUS_HANDS_STATE', 'ATTICUS_RELAY_OWNER', 'ATTICUS_LIVE'):
        os.environ.pop(key, None)
    if live:
        os.environ.pop('ATTICUS_CLAUDE', None)
    Path(os.environ['ATTICUS_COMMIT']).write_text('1')

    try:
        att = _import_atticus(repo)
    except BaseException:
        stack.close()
        raise
    att.INNER = False  # top-level ask, not a nested tool process
    clarify = {'n': 0}

    def auto_ask(j, secs):
        if j.get('retry'):
            return 'n'
        if j.get('pick'):
            clarify['n'] += 1
            return '0'
        if j.get('set'):
            return 'ok'
        if j.get('q'):
            if '?' in j.get('q', ''):
                clarify['n'] += 1
            return 'y'
        return None

    started = time.time()
    ran = []
    cost = 0
    relay_stop = threading.Event()

    def watch_ask():
        while not relay_stop.is_set():
            d = os.environ.get('ATTICUS_ASK')
            if d:
                _auto_allow(d, relay_stop)
            time.sleep(0.05)

    watcher = threading.Thread(target=watch_ask, daemon=True)
    real_run, real_popen = subprocess.run, subprocess.Popen
    def run(args, **kwargs):
        return fake_mac.run(args, **kwargs) or real_run(args, **kwargs)
    def popen(args, **kwargs):
        return fake_mac.popen(args, **kwargs) or real_popen(args, **kwargs)

    patches = [
        mock.patch.object(subprocess, 'run', run),
        mock.patch.object(subprocess, 'Popen', popen),
        mock.patch.object(att, 'DIR', scratch.name),
        mock.patch.object(att, 'licensed', return_value=True),
        mock.patch.object(att, 'ping', return_value=None),
        mock.patch.object(att, 'wait_commit', return_value=True),
        mock.patch.object(att, 'front', return_value=(scenario.get('front_app', 'Fixture'), scenario.get('front_window', 'Fixture'))),
        mock.patch.object(att, 'osa', return_value=''),
        mock.patch.object(att, 'screens', return_value=[('Built-in', 0, 0, 1400, 900, True)]),
        mock.patch.object(att, 'describe', return_value='one screen'),
        mock.patch.object(att, 'selection_context', return_value=''),
        mock.patch.object(att, 'relevant_rules', return_value=''),
        mock.patch.object(att, 'recent', return_value=[]),
        mock.patch.object(att, 'workflows', return_value=''),
        mock.patch.object(att, 'tool_help', return_value=''),
        mock.patch.object(att, 'hands_map', return_value=None),
        mock.patch.object(att, 'screen_for', return_value=None),
        mock.patch.object(att, 'look', return_value=[]),
        mock.patch.object(att, 'restore_focus', return_value=None),
        mock.patch.object(att, 'remember_turn', return_value=None),
        mock.patch.object(att, 'learn', return_value=False),
        mock.patch.object(att, 'tip', return_value=None),
        mock.patch.object(att, 'emit', return_value=None),
        mock.patch.object(att, 'report', return_value=None),
        mock.patch.object(att, 'POSTHOG_KEY', ''),
        mock.patch.object(att, 'pref', side_effect=lambda k, d: True if k in ('safe', 'improveAsked') else d),
        mock.patch.object(att, 'ask_user', side_effect=auto_ask),
        mock.patch('sys.argv', [str(atticus_path), scenario['task']]),
        mock.patch('sys.stdout', io.StringIO()),
        mock.patch.object(att.os, 'setpgrp'),
        mock.patch.object(att.signal, 'signal'),
    ]
    with stack:
        for p in patches:
            stack.enter_context(p)
        watcher.start()
        try:
            att.main()
        finally:
            relay_stop.set()

    log = Path(scratch.name) / 'log.jsonl'
    reply = ''
    if log.exists():
        rows = att.read_rows(str(log))
        if rows:
            cost = rows[-1].get('usd', 0)
            ran = rows[-1].get('ran', []) or getattr(att.run, 'ran', [])
            reply = rows[-1].get('reply', '') or ''
    else:
        ran = getattr(att.run, 'ran', []) or []

    front_text_chars = 0
    wt = Path(scratch.name) / 'window-text.json'
    if wt.is_file():
        try:
            front_text_chars = len(json.loads(wt.read_text()).get('text', ''))
        except (OSError, ValueError):
            pass

    final_state = json.load(open(state_path))
    metrics = {'seconds': time.time() - started, 'usd': cost, 'round_trips': len(ran), 'risky_without_allow': 0,
               'front_text_chars': front_text_chars}
    result = score(scenario, ran, final_state, metrics, clarify_count=clarify['n'], live=live, reply=reply)
    result['reply'] = reply
    scratch.cleanup()
    return result


def run_all(repo, live=False, ids=None, out_json=None):
    from tests.evals.scenarios import SCENARIOS

    rows = []
    for scenario in SCENARIOS:
        if ids and scenario['id'] not in ids:
            continue
        try:
            rows.append(run_scenario(scenario, repo, live=live))
        except Exception as e:
            rows.append({'id': scenario['id'], 'ok': False, 'round_trips': 0, 'seconds': 0, 'usd': 0,
                         'notes': f'harness error: {e}', 'effects': [], 'cmds': []})
    if out_json:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text(json.dumps(rows, indent=2) + '\n')
    return rows


def print_table(rows):
    hdr = f"{'scenario':<22} {'pass':<5} {'trips':<6} {'secs':<7} notes"
    print(hdr)
    print('-' * len(hdr))
    for r in rows:
        print(f"{r['id']:<22} {str(r['ok']):<5} {r['round_trips']:<6} {r['seconds']:<7} {r['notes'][:60]}")


def main():
    from tests.evals.scenarios import SCENARIOS

    p = argparse.ArgumentParser(description='Atticus task eval harness')
    p.add_argument('--repo', default=str(ROOT), help='Atticus worktree (atticus.py root)')
    p.add_argument('--dry', action='store_true', help='Scripted Claude (CI / VM)')
    p.add_argument('--live', action='store_true', help='Real claude -p on this Mac')
    p.add_argument('--id', action='append', help='Run only these scenario ids')
    p.add_argument('--out', default='', help='Write JSON results path')
    p.add_argument('--max', type=int, default=20, help='Max scenarios for live')
    args = p.parse_args()
    if args.live and args.dry:
        p.error('choose --dry or --live, not both')
    live = args.live
    if not args.live and not args.dry:
        live = False
    ids = args.id
    scenarios = [s for s in SCENARIOS if not ids or s['id'] in ids]
    if live and len(scenarios) > args.max:
        scenarios = scenarios[:args.max]
        ids = [s['id'] for s in scenarios]
    out = args.out or str(Path(args.repo) / '.agents' / 'evals-last.json')
    rows = run_all(args.repo, live=live, ids=ids, out_json=out)
    print_table(rows)
    print(f'\nJSON: {out}')
    return 0 if all(r['ok'] for r in rows) else 1


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
