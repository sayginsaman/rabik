"""run(): one ask through the AI client (Claude Code, Devin or Pi), streaming its steps and answer to the box."""
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from brain import (
    agents, clients, handoffs, interaction, labels, macos, messages, paths, policy, prefs, prompts, protocol, situation,
    storage, telemetry, turn, web)

__all__ = ['run', 'run_devin', 'run_pi']


def run(task, p=None, shots=(), auto_work=False, *, request=None, main_only=False, routing_retry=False):
    """One request through the configured client (the user's plan), streaming notes and steps. shots: [(path, label)] sent with it."""
    run.cmds = run.ran = []
    run.error = ''
    run.ok = False
    run.handoff, run.handoffs = None, []
    run.observed = []
    run.work = False   # set before the Devin/Pi paths too: main() reads run.work after every client
    run.why = ''   # why it failed, one fixed word for PostHog
    if prefs.client() == 'devin':
        return run_devin(task, shots, request=request)
    if prefs.client() == 'pi':
        return run_pi(task, shots, request=request)
    main_only = main_only or situation.main_delivery_required()
    p = p or clients.start_claude()
    if not p:
        protocol.say('!', 'setup')   # Rabik.app opens its setup window
        return clients.plan()['text'] + ' Rabik setup is open to fix it.', 0, []
    if getattr(p, 'ask', ''):
        agents.save_request(p.ask, messages.main_ask(task, request)[0])
    content = messages.user_content(task, shots, request)
    if main_only:
        content.insert(0, {'type': 'text', 'text': 'This request requires main-window delivery. Finish here; do not emit agent, steer, or agent-profile run directives.'})
    message = json.dumps({'type': 'user', 'message': {'role': 'user', 'content': content}}) + '\n'
    try:
        p.stdin.write(message); p.stdin.close()
    except (BrokenPipeError, ValueError):   # the warm worker quit before the ask (crash, sign-out, sleep): one fresh start
        clients.stop_claude(p); p = clients.start_claude(getattr(p, 'rabik_model', None))
        if not p:
            protocol.say('!', 'setup')
            return clients.plan()['text'] + ' Rabik setup is open to fix it.', 0, []
        if getattr(p, 'ask', ''): agents.save_request(p.ask, messages.main_ask(task, request)[0])
        p.stdin.write(message); p.stdin.close()
    p.waiting = threading.Event()
    if getattr(p, 'ask', '') and getattr(p, 'relaying', False) is not True and os.environ.get('RABIK_RELAY_ACTIVE') != str(os.getpid()):
        p.relaying = True
        p.relay_thread = threading.Thread(target=interaction.relay, args=(p,), daemon=True)
        p.relay_thread.start()
    step_base = len(turn.TURN.get('step_times', []))
    ran_base = turn.TURN.get('ran', [])[:]
    deadline, generation, deadline_lock, timed_out = [None], [0], threading.Lock(), [False]
    def expire(current):
        with deadline_lock:
            if current != generation[0]: return
        if p.waiting.is_set():
            reset_deadline()
            return
        timed_out[0] = True
        turn.end_turn('timed_out'); clients.stop_claude(p)
    def reset_deadline():
        with deadline_lock:
            generation[0] += 1
            if deadline[0]: deadline[0].cancel()
            deadline[0] = threading.Timer(180, expire, args=(generation[0],))
            deadline[0].daemon = True
            deadline[0].start()
    def cancel_deadline():
        with deadline_lock:
            generation[0] += 1
            if deadline[0]: deadline[0].cancel()
    p.progress = reset_deadline
    reset_deadline()
    reply, managed_reply, cost, steps, cmds, last_failed, completed, result_error, ids, bad = '', '', 0, [], [], False, False, False, {}, set()
    action_indexes, evidence, redirected = [], False, set()
    live, shown, drew = '', '', False   # the answer so far, as the box shows it ("… <text>"); the final reply always replaces it
    streams = os.environ.get('RABIK_UI') == '1' and prefs.pref('showAnswers', 'stream') != 'once'   # Settings › Show answers: All at once
    # a draft for the caret shows its mode only in the final answer, so a cursor ask never moves mid-way
    move = handoffs.MainMove(task, p, request) if not main_only and not os.environ.get('RABIK_CARET') and getattr(p, 'ask', '') and os.environ.get('RABIK_UI') == '1' else None
    if move:
        move.thread = threading.Thread(target=move.watch, daemon=True); move.thread.start()
    try:
        for line in p.stdout:
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if not isinstance(j, dict): continue
            if (run.handoff or managed_reply) and j.get('type') != 'result': continue
            if j.get('type') == 'stream_event':
                event = j.get('event') if isinstance(j.get('event'), dict) else {}
                block, delta = (event.get(k) if isinstance(event.get(k), dict) else {} for k in ('content_block', 'delta'))
                if event.get('type') == 'message_start' or block.get('type') == 'tool_use':   # a tool call: the text before it was a note
                    live = None if block.get('type') == 'tool_use' else ''
                    if shown: protocol.say('…', ''); shown = ''
                elif delta.get('type') == 'text_delta' and isinstance(delta.get('text'), str) and live is not None:
                    live += delta['text']
                    commit = os.environ.get('RABIK_COMMIT')
                    text = handoffs.streamed_answer(live) if streams and not drew and (not commit or os.path.exists(commit)) else ''
                    if text != shown: protocol.say('…', text); shown = text
                continue
            if move:
                move.record(j)
                if j.get('type') == 'assistant': move.poll()
            if j.get('type') == 'assistant':
                blocks = messages.message_blocks(j)
                directives = handoffs.parse_handoffs(''.join(b.get('text', '') for b in blocks if b.get('type') == 'text' and isinstance(b.get('text'), str)))
                directive = directives[0] if directives else None
                if directive and not any(b.get('type') == 'tool_use' for b in blocks) and os.environ.get('RABIK_UI') == '1':
                    if main_only and any(not (d.get('steer') or d.get('namedAction')) for d in directives):
                        clients.stop_claude(p)
                        if not routing_retry:
                            model = getattr(p, 'rabik_model', None)
                            reply, _, retry_steps = run(task, clients.start_claude(model if isinstance(model, str) else None), shots,
                                                        request=request, main_only=True, routing_retry=True)
                            return reply, None, retry_steps   # interrupted attempt has no terminal usage receipt
                        run.error = 'The model tried to hand off a request that needs the main window.'
                        return 'Could not finish this in the main window. Please try again.', 0, []
                    if move:
                        move.close()
                        if move.moved: continue   # ⌃⌥↩ won the race: that move is this ask's one hand-off
                    if not interaction.wait_commit():
                        clients.stop_claude(p)
                        return '', None, steps
                    if directive.get('namedAction'):
                        outcome = handoffs.named_agent_action(directive['namedAction'])
                        managed_reply = outcome.get('reply', '')
                        if managed_reply: continue
                        directives = [outcome['handoff']]
                    confirmed, context = messages.main_ask(task, request)
                    if run.observed: context = handoffs.handoff_context(context, run.observed)
                    for handoff in directives:
                        brief = str(handoff.get('brief', '')).replace(prompts.MODEL_OFFER, '').replace(prompts.MODEL_OFFER.strip(), '').strip() or confirmed[:1000]
                        app = web.running_app(handoff['app']) if handoff.get('app') else os.environ.get('RABIK_FRONT', '')   # unnamed: the window the user asked over
                        page = web.work_page(app, handoff.get('page', ''), getattr(p, 'ask', '')) if app else {}
                        run.handoffs.append({**handoff, 'brief': brief, 'context': context, 'request': confirmed, 'app': app or os.environ.get('RABIK_FRONT', ''), 'page': page})
                        handoffs.persist_handoff(run.handoffs[-1], p.pid)
                        if run.handoff is None:
                            run.handoff = run.handoffs[0]
                            storage.private_json(os.path.join(p.ask, 'handed-off'), True)
                        print('⤴ ' + json.dumps(run.handoffs[-1], ensure_ascii=False), flush=True)
                    continue   # drain the result for actual plan usage; the native box is already free
                if any(b.get('type') == 'tool_use' for b in blocks):   # notes before a tool call; the final text comes as result
                    for b in blocks:
                        text = handoffs.without_handoff_line(b.get('text')) if isinstance(b.get('text'), str) else ''
                        if b.get('type') == 'text' and text.strip():
                            protocol.say('·', text)
                        elif b.get('type') == 'tool_use':
                            if not isinstance(b.get('name'), str) or not isinstance(b.get('input'), dict): continue
                            name, inp = b['name'], b['input']
                            drew = drew or bool(re.search(r'--draw\b|--point\b', str(inp)))   # a guide or pointer replaces the answer text
                            if name == 'WebSearch' and policy.search_first(getattr(p, 'ask', '')):
                                redirected.add(b.get('id')); continue
                            p.waiting.clear()
                            reset_deadline()
                            steps.append(labels.label(name, inp))
                            protocol.say('▸', steps[-1])
                            if turn.TURN:
                                turn.TURN['step_times'].append({'label': steps[-1], 'secs': 0, 'status': 'running', '_start': time.monotonic()})
                            ids[b.get('id')] = len(cmds)
                            command = inp.get('command') or ''
                            if name == 'Bash' and not policy.agent_read_command(command):
                                run.work = True; action_indexes.append(len(cmds))
                            cmds.append(command or f"<{name or 'tool'}>")   # non-Bash tools block learning
                            turn.checkpoint(steps=[s['label'] for s in turn.TURN.get('step_times', [])], ran=ran_base + cmds)
            elif j.get('type') == 'user':   # tool results
                results = [b for b in messages.message_blocks(j) if b.get('type') == 'tool_result' and not (b.get('is_error') and b.get('tool_use_id') in redirected)]
                if results:
                    p.waiting.clear()
                    reset_deadline()
                    last_failed = any(b.get('is_error') for b in results)
                    bad |= {ids.get(b.get('tool_use_id')) for b in results if b.get('is_error')}
                    for b in results:
                        run.observed.append({'action': cmds[ids[b.get('tool_use_id')]] if b.get('tool_use_id') in ids else '',
                                             'error': bool(b.get('is_error')), 'result': b.get('content', '')})
                        i = ids.get(b.get('tool_use_id'))
                        content = b.get('content', '')
                        if isinstance(content, list):
                            content = '\n'.join(str(part.get('text', '')) for part in content if isinstance(part, dict))
                        if b.get('is_error') and str(content).strip():
                            run.error = telemetry.clean(str(content))
                        if i is not None and action_indexes and i >= action_indexes[0] and not b.get('is_error') and str(content or '').strip():
                            evidence = True
                        if i is not None and turn.TURN:
                            step = turn.TURN['step_times'][step_base + i]
                            step.update(secs=round(time.monotonic() - step.pop('_start', time.monotonic()), 3), status='failed' if b.get('is_error') else 'completed')
                            turn.checkpoint()
                        if i is not None and not b.get('is_error'): macos.preview_commands(cmds[i], getattr(p, 'ask', None))
            elif j.get('type') == 'result':
                if move: move.close()
                p.waiting.clear()
                cancel_deadline()
                completed = True
                result_error = bool(j.get('is_error'))
                result = j.get('result') if isinstance(j.get('result'), str) else ''
                total = j.get('total_cost_usd', 0)
                if turn.TURN:
                    receipt = {key: j[key] for key in ('usage', 'modelUsage') if isinstance(j.get(key), dict)}
                    if receipt: turn.TURN.setdefault('attempt_usage', []).append(receipt)
                reply, cost = handoffs.without_handoff_line(managed_reply or result), total if type(total) in (int, float) else 0
                turn.checkpoint(reply='' if result_error else reply, usd=(turn.TURN.get('usd') or 0) + cost)
                break
        try: p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            clients.stop_claude(p); p.wait()
    finally:
        if move: move.close()
        cancel_deadline()
        if sys.exc_info()[0] is not None: clients.stop_claude(p)
    if getattr(p, 'relay_thread', None): p.relay_thread.join(.3)   # drain target/point events before the final answer
    if managed_reply and not reply: reply, completed = managed_reply, True
    if move and move.moved:
        if not interaction.wait_commit(): return '', None, steps
        run.handoff = move.pending; run.handoffs = [run.handoff]
        if not completed: cost = None   # the interrupted CLI did not provide terminal usage; zero would be misleading
        turn.end_turn('handed_off', emit=False)
        print('⤴ ' + json.dumps(run.handoff, ensure_ascii=False), flush=True)
    if run.handoff:
        run.ok = True
        run.ran = cmds
        return '', cost, steps
    run.ran = cmds   # the exact commands, for the ask log
    if result_error or (not reply and p.returncode):
        c = {'ok': True} if result_error else clients.plan()
        if not c['ok']:
            protocol.say('!', 'setup')
        p.errors.seek(0)
        detail = '\n'.join(filter(None, [reply if result_error else '', p.errors.read(2000).strip()]))
        run.error = telemetry.clean(detail)
        custom = bool(prefs.server())
        if not c['ok']:
            run.why = 'setup_needed'; reply = c['text'] + ' Rabik setup is open to fix it.'
        elif re.search(r'\b(?:o?auth(?:enticate|entication|orization)?|unauthori[sz]ed)\b|\b401\b|invalid (?:api )?key|not logged in|sign.?in', detail, re.I):
            run.why = 'signed_out'
            if custom:
                reply = 'Your custom server rejected its credentials. Check its key in Settings.'
            else:
                protocol.say('!', 'setup')
                reply = 'Your Claude sign-in expired. Rabik setup is open to sign in again.'
        elif re.search(r'rate.?limit|usage limit|too many requests|\b429\b', detail, re.I):
            run.why = 'rate_limited'; reply = ('Your custom server' if custom else 'Claude') + ' is temporarily rate-limited. Please try again in a moment.'
        elif re.search(r'network|connect|dns|timed? ?out|timeout', detail, re.I):
            run.why = 'offline'; reply = ('Could not connect to your custom server. Check its address and try again.' if custom else
                     'Claude could not connect. Check your internet connection and try again.')
        elif re.search(r'overload|unavailable|service error|\b5\d\d\b', detail, re.I):
            run.why = 'unavailable'; reply = ('Your custom server' if custom else 'Claude') + ' is temporarily unavailable. Please try again.'
        elif re.search(r'sandbox', detail, re.I):
            run.why = 'sandbox'; reply = 'Claude’s sandbox could not start. Open Rabik Settings → Account & Access → Safety, turn off Safe mode, and try again.'
        else:
            protocol.say('!', 'setup'); run.why = 'stopped'
            reason = ' '.join(telemetry.clean(detail).split()) or f'exit code {p.returncode}'
            reply = f'{"Your custom server" if custom else "Claude"} stopped: {reason}. Rabik setup is open; choose Set Up, then try again.'
    if auto_work and reply.endswith('[done]'):   # accepted from older warmed prompts during an update
        reply = reply[:-6].rstrip()
    # a step that failed and was then done another way is dropped, so the way that worked can still be learned
    base_ok = bool(completed and reply and not result_error and not p.returncode and not last_failed and not timed_out[0] and reply != '[sonnet]')
    verified = not run.work or evidence
    run.cmds = [c for i, c in enumerate(cmds) if i not in bad] if base_ok and verified else []
    run.ok = base_ok and verified
    if not run.ok and not run.why:
        run.why = next(w for w, hit in (('timed_out', timed_out[0]), ('not_finished', not completed), ('tool_failed', last_failed),
                                        ('unverified', base_ok), ('no_reply', not reply), ('other', True)) if hit)
    if base_ok and not verified:
        run.error = 'The action returned no observable result.'
        claim = re.split(r'(?<=[.!?])\s+', ' '.join(reply.split()), maxsplit=1)[0][:140].rstrip(' .')
        reply = f'{claim} — but I couldn’t confirm the result.' if claim else 'I tried the requested action, but I couldn’t confirm the result.'
    if not reply and last_failed and not result_error and not p.returncode:
        reply = 'The last tool failed, so I could not verify that the request was completed. Please try again.'
    if not reply:
        if completed:
            reply = 'Claude returned an empty answer. Please try again.'
        else:
            protocol.say('!', 'setup')
            reply = 'Claude’s helper exited without returning a result. Rabik setup is open; choose Set Up, then try again.'
    blocked = re.search(r'\b(block(?:ed)?|denied|not allowed|permission)\b|hook', run.error, re.I) or re.search(r'\btool\b.{0,30}\bblocked\b', reply, re.I)
    if last_failed and blocked and run.error.casefold() not in reply.casefold():
        reply = (reply.rstrip() + ' Tool reported: ' + run.error).strip()
    if callable(getattr(getattr(p, 'stdout', None), 'close', None)):
        p.stdout.close()
    if callable(getattr(getattr(p, 'errors', None), 'close', None)):
        p.errors.close()
    return reply, cost, steps


def run_devin(task, shots=(), request=None):
    """One confirmed request through `devin -p`; its project config gates tools and forbids direct writes."""
    run.cmds = run.ran = []
    run.error = ''
    run.ok = False
    if not shutil.which('devin'):
        protocol.say('!', 'setup')   # Rabik.app opens its setup window
        return clients.plan()['text'] + ' Rabik setup is open to fix it.', 0, []
    if not interaction.wait_commit():
        return 'The request was cancelled before the transcript was confirmed.', 0, []
    ask = tempfile.mkdtemp(prefix='rabik-ask-')   # the choices card (and hands events) talk through it
    atexit.register(shutil.rmtree, ask, True)   # however this run ends
    agents.save_request(ask, messages.main_ask(task, request)[0])
    prompt = prompts.system_prompt(prompts.ASK_FIRST if prefs.pref('safe', True) else prompts.NEVER)
    if shots:
        prompt += '\nScreen pictures (read them if your tools can view images): ' + ', '.join(path for path, _ in shots)
    prompt += '\n\n' + '\n\n'.join(b['text'] for b in messages.user_content(task, request=request))
    config = clients.devin_config(ask)
    errors = tempfile.TemporaryFile(mode='w+')   # draining a pipe only after wait() can deadlock
    try:
        p = subprocess.Popen(['devin', '-p', prompt, '--permission-mode', 'normal', '--config', config, '--respect-workspace-trust', 'false'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors, text=True,
                             cwd=ask, start_new_session=True,
                             env={**os.environ, 'RABIK_ASK': ask})
    except BaseException:
        errors.close()
        raise
    p.ask, p.errors = ask, errors
    atexit.register(errors.close)
    atexit.register(clients.stop_devin, p, ask)
    signal.signal(signal.SIGTERM, lambda *_: (clients.stop_devin(p, ask), clients.stop_workers()))
    p.relay_thread = threading.Thread(target=interaction.relay, args=(p,), daemon=True)   # pick/set/point cards, as for Claude
    p.relay_thread.start()
    timed_out = False
    try:
        reply, _ = p.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        timed_out = True
        clients.stop_claude(p)
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        reply = 'Devin timed out before finishing. Please try again.'
        run.error = reply
    reply = handoffs.without_handoff_line(reply)
    p.relay_thread.join(.3)
    deleted = clients.delete_devin_session(ask)
    rows = storage.read_rows(os.path.join(ask, 'devin-tools.jsonl'))
    steps = [row.get('step', '') for row in rows if row.get('step')]
    run.ran = [row['input']['command'] for row in rows if row.get('tool') == 'exec' and row.get('input', {}).get('command')]
    if p.returncode and not timed_out:
        c = clients.plan()   # the usual cause: not installed or signed out
        if not c['ok']:
            protocol.say('!', 'setup')
        p.errors.seek(0)
        detail = p.errors.read(200).strip() or reply[:200]
        run.error = telemetry.clean(detail)
        if not c['ok']:
            reply = c['text'] + ' Rabik setup is open to fix it.'
        else:
            protocol.say('!', 'setup')
            reply = f'Devin stopped: {telemetry.clean(detail) or f"exit code {p.returncode}"}. Rabik setup is open; choose Set Up, then try again.'
    success = bool(reply and not p.returncode and not timed_out)
    if not deleted:
        warning = 'Rabik could not delete Devin’s saved session. Remove it in Devin before continuing.'
        reply = f'{reply} {warning}'.strip()
    run.ok = success
    if p.stdout:
        p.stdout.close()
    errors.close()
    return reply or 'Devin returned an empty answer. Please try again.', 0, steps


def run_pi(task, shots=(), request=None):
    """One confirmed request through Pi's selected provider/model; an explicit extension sends every tool through Rabik's gate."""
    run.cmds = run.ran = []
    run.error = ''
    run.ok = False
    pi = shutil.which('pi')
    if not pi:
        protocol.say('!', 'setup')
        return clients.plan()['text'] + ' Rabik setup is open to fix it.', 0, []
    if not interaction.wait_commit():
        return 'The request was cancelled before the transcript was confirmed.', 0, []
    ask = tempfile.mkdtemp(prefix='rabik-ask-')
    atexit.register(shutil.rmtree, ask, True)
    agents.save_request(ask, messages.main_ask(task, request)[0])
    extension = os.path.join(ask, 'rabik-gate.ts')
    with open(extension, 'w') as f:
        f.write(clients.PI_GATE)
    errors = tempfile.TemporaryFile(mode='w+')
    args = [pi, '--mode', 'json', '--print', '--no-session', '--no-mcp', '--no-skills', '--no-prompt-templates',
            '--no-context-files', '--no-extensions', '--extension', extension,
            '--system-prompt', prompts.system_prompt(prompts.ASK_FIRST if prefs.pref('safe', True) else prompts.NEVER),
            '--tools', 'bash,read,grep,find,ls', '--'] + ['@' + path for path, _ in shots if os.path.exists(path)] + ['\n\n'.join(b['text'] for b in messages.user_content(task, request=request))]
    env = {**os.environ, 'RABIK_ASK': ask, 'RABIK_CLIENT': 'pi', 'RABIK_ME': paths.ME}
    try:
        p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors, text=True,
                             cwd=ask, start_new_session=True, env=env)
    except BaseException:
        errors.close()
        raise
    p.ask, p.errors = ask, errors
    atexit.register(errors.close); atexit.register(clients.stop_claude, p)
    signal.signal(signal.SIGTERM, lambda *_: (clients.stop_claude(p), clients.stop_workers()))
    p.relay_thread = threading.Thread(target=interaction.relay, args=(p,), daemon=True); p.relay_thread.start()
    reply, cost, failed, timed_out = '', 0, False, [False]
    def expire():
        timed_out[0] = True
        clients.stop_claude(p)
    deadline = threading.Timer(180, expire); deadline.daemon = True; deadline.start()
    try:
        for line in p.stdout:
            try: event = json.loads(line)
            except ValueError: continue
            if not isinstance(event, dict): continue
            if event.get('type') == 'tool_execution_end':
                failed = bool(event.get('isError'))
            else:
                message = event.get('message')
                if event.get('type') != 'message_end' or not isinstance(message, dict) or message.get('role') != 'assistant': continue
                content = message.get('content', [])
                if isinstance(content, str): reply = handoffs.without_handoff_line(content)
                elif isinstance(content, list): reply = handoffs.without_handoff_line(''.join(block.get('text', '') for block in content if isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str)))
                usage = message.get('usage') if isinstance(message.get('usage'), dict) else {}
                costs = usage.get('cost') if isinstance(usage.get('cost'), dict) else {}
                if type(costs.get('total')) in (int, float): cost += costs['total']
        p.wait()
    finally:
        deadline.cancel()
        if sys.exc_info()[0] is not None and p.poll() is None: clients.stop_claude(p)
    p.relay_thread.join(.3)
    rows = storage.read_rows(os.path.join(ask, 'pi-tools.jsonl'))
    steps = [row.get('step', '') for row in rows if row.get('step')]
    cmds = [row['input']['command'] for row in rows if row.get('tool') == 'exec' and row.get('input', {}).get('command')]
    run.ran = cmds
    run.cmds = [] if failed or p.returncode or timed_out[0] or not reply else cmds
    run.ok = bool(reply and not failed and not p.returncode and not timed_out[0])
    if timed_out[0]:
        reply = 'Pi timed out before finishing. Please try again.'
    elif p.returncode:
        errors.seek(0); detail = errors.read(500).strip()
        run.error = telemetry.clean(detail)
        if re.search(r'auth|credential|model|provider|login', detail, re.I):
            protocol.say('!', 'setup')
            reply = 'Pi needs a provider and model. Rabik setup is open to fix it.'
        else:
            protocol.say('!', 'setup')
            reply = f'Pi stopped: {telemetry.clean(detail) or f"exit code {p.returncode}"}. Rabik setup is open; choose Set Up, then try again.'
    elif not reply and failed:
        reply = 'The last Pi tool failed, so I could not verify that the request was completed. Please try again.'
    if p.stdout:
        p.stdout.close()
    errors.close()
    return reply or 'Pi returned an empty answer. Please try again.', cost, steps
