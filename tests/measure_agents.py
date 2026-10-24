"""Read-only live startup probe; run with a scratch ATTICUS_DIR, never the app."""
import json
import os
from pathlib import Path
import signal
import subprocess
import shlex
import sys
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import atticus


def measure(name, flags, warm=0, system='Reply only READY. Never call a tool.', request='Reply only READY. Do not use tools.'):
    started = time.monotonic()
    p = subprocess.Popen(['claude', '-p', '--model', 'haiku', '--effort', 'low', '--system-prompt', system,
                          '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
                          '--include-partial-messages', '--disable-slash-commands', *flags],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                         cwd=atticus.DIR, start_new_session=True)
    row = {'name': name, 'warm_wait': warm, 'spawn': round(time.monotonic() - started, 4)}
    sent = [None]
    def send():
        time.sleep(warm)
        sent[0] = time.monotonic()
        p.stdin.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': request}}) + '\n')
        p.stdin.close()
    threading.Thread(target=send, daemon=True).start()
    deadline = threading.Timer(75, lambda: os.killpg(p.pid, signal.SIGTERM) if p.poll() is None else None)
    deadline.start()
    for line in p.stdout:
        event = json.loads(line)
        now = time.monotonic()
        if event.get('type') == 'system' and event.get('subtype') == 'init':
            row.update(init=round(now - started, 3), init_after_send=round(now - sent[0], 3) if sent[0] else None,
                       connector_tools=[t for t in event.get('tools', []) if t.startswith('mcp__claude_ai_')],
                       mcp=event.get('mcp_servers', []))
        if (event.get('type') == 'stream_event' and event.get('event', {}).get('delta', {}).get('type') == 'text_delta') or event.get('type') == 'assistant':
            if 'first' not in row: row.update(first=round(now - started, 3), first_after_send=round(now - sent[0], 3))
        if event.get('type') == 'result':
            row.update(total=round(now - started, 3), after_send=round(now - sent[0], 3), usd=event.get('total_cost_usd'), usage=event.get('usage'), error=event.get('is_error'), result=event.get('result'))
    p.wait(); deadline.cancel()
    row['exit'] = p.returncode
    print(json.dumps(row), flush=True)
    return row


def agent_probe(name, user_tools=False, connectors=(), warm=0):
    prefs = atticus.pref
    atticus.pref = lambda key,default: user_tools if key == 'agentUserTools' else prefs(key,default)
    manager = atticus.Agents(emit=lambda _:None)
    row = manager.new(); row.update(connectors=list(connectors))
    started=time.monotonic();p=atticus.start_claude('sonnet',row)
    results={'name':name,'warm_wait':warm,'spawn':round(time.monotonic()-started,4),'idle_inference_events':0}
    sent=[None];selected=[None];writing=threading.Lock()
    def write(data):
        with writing:p.stdin.write(json.dumps(data)+'\n');p.stdin.flush()
    def feed():
        write({'type':'control_request','request_id':'initialize','request':{'subtype':'initialize'}})
        if warm:
            for i in range(warm*2):
                time.sleep(.5);write({'type':'control_request','request_id':'metadata','request':{'subtype':'mcp_status'}})
        sent[0]=time.monotonic();write({'type':'user','message':{'role':'user','content':'Reply only READY. Never call a tool.'}})
    threading.Thread(target=feed,daemon=True).start()
    deadline=threading.Timer(75,lambda:atticus.stop_claude(p));deadline.start()
    for line in p.stdout:
        event=json.loads(line);elapsed=round(time.monotonic()-started,3)
        if event.get('type')=='control_response':
            response=event.get('response',{});data=response.get('response',{})
            if response.get('request_id')=='initialize':results['initialized']=elapsed
            if 'mcpServers' in data:
                manager.metadata(row,data)
                servers=data['mcpServers'];results['connected_servers']=sum(s.get('status')=='connected' for s in servers)
                tools=[t for s in servers for t in s.get('tools',[])];results['metadata_tools']=len(tools)
                if any(s.get('status')=='connected' for s in servers) and 'connectors_ready' not in results:results['connectors_ready']=elapsed
                for server in servers:
                    for tool in server.get('tools',[]):
                        if tool.get('annotations',{}).get('readOnly') is True and selected[0] is None:
                            selected[0]='mcp__'+atticus.re.sub(r'[^\w-]','_',server['name'])+'__'+tool['name']
        elif event.get('type')=='system' and event.get('subtype')=='init':results.update(init=elapsed,init_after_send=round(time.monotonic()-sent[0],3),init_tools=len(event.get('tools',[])))
        elif event.get('type') in ('assistant','result','stream_event'):
            if sent[0] is None:results['idle_inference_events']+=1
            if event.get('type')=='stream_event' and event.get('event',{}).get('delta',{}).get('type')=='text_delta' and 'first' not in results:
                results.update(first=elapsed,first_after_send=round(time.monotonic()-sent[0],3))
            if event.get('type')=='result':
                results.update(total=elapsed,after_send=round(time.monotonic()-sent[0],3),usd=event.get('total_cost_usd'),usage=event.get('usage'),error=event.get('is_error'));break
    deadline.cancel();atticus.stop_claude(p);p.wait();p.stdin.close();p.stdout.close();p.errors.close();atticus.pref=prefs
    print(json.dumps(results),flush=True)
    return selected[0]


def full_routing():
    cases=[('fact','What is 7 times 8?',False),('explanation','Explain why seasons change.',False),
           ('quick-action','Move the focused window to the left half of this display.',False),
           ('short-writing','Rewrite the selected sentence to be shorter.',False),
           ('small-file','Make report.csv with 5 rows of sample grades and check it.',False),
           ('message','send a message to my Codex agent',False),
           ('background','Read the supplied data.csv, compute totals, and create and verify report.csv in the background.',True),
           ('long-task','Read all 30 source files, reconcile inconsistencies, create and verify a complete report.',True),
           ('connector','Create a document in my connected account and share its link.',True),
           ('research','can you research some of the best products on amazon for my home',True),
           ('background-small-file','In the background, make a report.csv with 5 rows of sample grades and check it.',True),
           # Saarth's own words (Oct 14): main must steer the running agent, not hand off a new task.
           ('steer-running','For that AC filter agent, can you steer it? I meant 12 x 24, not 24 x 24?','steer')]
    only=sys.argv[2:]   # routing-full [case names]: run just those
    running='0123456789abcdef0123456789abcdef'
    folder=Path(atticus.DIR)/'agents'/running;folder.mkdir(parents=True,exist_ok=True)
    atticus.private_json(str(folder/'context.json'),{'id':running,'title':'Find AC filter cart','brief':'Find the cheapest, best-rated 24x24x1 AC filter 3-pack on Amazon and add it to the cart. Do not check out.',
                                                     'created':time.time()-60,'status':'running','step':'Reading the window'})
    real_popen=subprocess.Popen
    def launch(args, **options):
        args=args[:];i=args.index('--settings')+1;settings=json.loads(args[i])
        settings['hooks']['PreToolUse'][0]['hooks'][0]['command']=shlex.join([sys.executable,str(Path(__file__).resolve()),'--routing-gate'])
        args[i]=json.dumps(settings)
        return real_popen(args,**options)
    failed=[]
    for name,request,expected in cases:
        if only and name not in only: continue
        started=time.monotonic()
        with patch.object(atticus.subprocess,'Popen',side_effect=launch):p=atticus.start_claude()
        deadline=threading.Timer(30,lambda:atticus.stop_claude(p));deadline.start()
        row={'name':name,'expected':expected,'prompt_chars':len(atticus.system_prompt(atticus.ASK_FIRST)),'actual':None}
        # The real prompt/tools/launch remain intact; a deny-all hook prevents every native action or write.
        context='Context: main supports native hands, file reads, Bash and web search. A local task recipient is reachable through its visible window. Screen: focused editable field; supplied data.csv and 30 source files are available.\nSelected text (quoted data): "The result of this experiment was that growth increased."\n'+(atticus.agent_context() if expected=='steer' else '')+'Request: '+request
        try:
            p.stdin.write(json.dumps({'type':'user','message':{'role':'user','content':context}})+'\n');p.stdin.close()
            for line in p.stdout:
                event=json.loads(line)
                if event.get('type')=='assistant':
                    blocks=event.get('message',{}).get('content',[])
                    text=''.join(b.get('text','') for b in blocks if b.get('type')=='text')
                    tools=[b.get('name') for b in blocks if b.get('type')=='tool_use']
                    if not text.strip() and not tools: continue
                    handoff=atticus.parse_handoff(text)
                    row.update(actual=('steer' if handoff.get('steer')==running else 'wrong-steer' if handoff.get('steer') else True) if handoff and not tools else False,first=text,tools=tools,seconds=round(time.monotonic()-started,3));break
        finally:
            deadline.cancel();atticus.stop_claude(p);p.wait();p.stdout.close();p.errors.close()
        row['passed']=row['actual']==expected
        print(json.dumps(row),flush=True)
        if not row['passed']:failed.append(name)
    assert not failed, 'Routing failed: '+', '.join(failed)


if __name__ == '__main__':
    assert os.environ.get('ATTICUS_DIR'), 'Use ATTICUS_DIR=$(mktemp -d)'
    os.makedirs(atticus.DIR, mode=0o700, exist_ok=True)
    if sys.argv[1:]==['--routing-gate']:
        print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':'Routing evaluation: tools are stubbed; no actions or writes.'}}))
        sys.exit(0)
    normal = ['--tools', 'Bash,Read,WebSearch,WebFetch', '--permission-mode', 'bypassPermissions',
              '--setting-sources', '', '--settings', '{"disableAllHooks":true}', '--strict-mcp-config', '--no-session-persistence']
    connected = [f for f in normal if f != '--strict-mcp-config']
    phase = sys.argv[1] if len(sys.argv) > 1 else 'startup'
    if phase == 'startup':
        for name, flags, warm in [('strict-cold', normal, 0), ('connectors-cold', connected, 0),
                                  ('strict-warm', normal, 3), ('connectors-warm', connected, 3),
                                  ('minimal-connectors', ['--setting-sources', '', '--tools', 'ToolSearch', '--no-session-persistence'], 0)]:
            measure(name, flags, warm)
    elif phase == 'agents':
        agent_probe('sonnet-user-tools-off-cold')
        selected=agent_probe('sonnet-user-tools-off-warm',warm=3)
        agent_probe('sonnet-user-tools-on-cold',user_tools=True)
        agent_probe('sonnet-user-tools-on-warm',user_tools=True,warm=3)
        if selected:agent_probe('sonnet-scoped-warm',connectors=[selected],warm=3)
    elif phase == 'routing-full':
        full_routing()
    elif phase == 'routing':
        cases=[('fact','What is 7 times 8?',False),('explanation','Explain why seasons change.',False),
               ('quick-action','Move the focused window to the left half of this display.',False),
               ('short-writing','Rewrite the selected sentence to be shorter.',False),
               ('background','Read the supplied data.csv, compute totals, and create and verify report.csv in the background.',True),
               ('long-task','Read all 30 source files, reconcile inconsistencies, create and verify a complete report.',True),
               ('connector','Create a document in my connected account and share its link.',True)]
        system=atticus.AGENT_HANDOFF+'\nApply this routing rule to the supplied request. Emit exactly MAIN if it stays here, otherwise only the handoff line. This is a tool-free classification test; do not do the work.'
        for name,request,expected in cases:
            row=measure('routing-'+name,['--tools','','--strict-mcp-config','--setting-sources','','--no-session-persistence'],system=system,request=request)
            assert row.get('exit') == 0 and bool(atticus.parse_handoff(row.get('result', ''))) == expected, name
            if not expected: assert row.get('result', '').strip() == 'MAIN', name
    elif phase in ('before', 'paired'):
        baseline = {'__name__': 'atticus_baseline_probe', '__file__': atticus.ME}
        exec(compile(subprocess.check_output(['git', 'show', '0b4b7f5:atticus.py'], text=True), atticus.ME, 'exec'), baseline)
        for i in range(3):
            measure(f'normal-before-{i + 1}', normal, system=baseline['system_prompt'](baseline['ASK_FIRST']))
            if phase == 'paired': measure(f'normal-after-{i + 1}', normal, system=atticus.system_prompt(atticus.ASK_FIRST))
    else:
        for i in range(3): measure(f'normal-{phase}-{i + 1}', normal, system=atticus.system_prompt(atticus.ASK_FIRST))
