"""Hand-offs: the model's [handoff] directives, named agents, and MainMove (an ask that moves to the main window)."""
import json
import os
import re
import threading
import time
import uuid
from brain import clients, environ, macos, messages, paths, policy, storage, web, wording

__all__ = ['tag_json', 'HANDOFF_TAG', 'parse_handoff', 'parse_handoffs', 'without_handoff_line', 'streamed_answer',
           'persist_handoff', 'named_agents', 'save_named_agents', 'named_agent_action', 'handoff_context', 'agent_title',
           'MainMove']


def agent_title(request):
    case = {w.lower(): w for w in re.findall(r"[\w'$-]+", request)}
    skip = wording.STOP | wording.FILLER | set('by too have has had am are was were will should does did'.split())   # closed-class words never name a task
    words = max((list(dict.fromkeys(w for w in re.findall(r"[a-z0-9'.-]+", wording.plain(c)) if w not in skip)) for c in wording.MORE.split(request)[::2]), key=len, default=[])   # the step with the most words that matter: "Can you do the steps and get me the API key" -> "Get API key"
    title = ' '.join(case.get(w, w) for w in words[:5])[:80]
    return title[:1].upper() + title[1:] or 'Background task'


def tag_json(text, start):
    """The JSON object opening a [tag {...}] at start, closed by ']': pretty-printed JSON and text after it are fine."""
    try: data, end = json.JSONDecoder().raw_decode(text, start)
    except ValueError: return None
    return data if isinstance(data, dict) and text[end:].lstrip().startswith(']') else None


HANDOFF_TAG = re.compile(r'\s*(?:```\w*\s*)*\[(agent|steer|agent-profile)\s+(?=\{)')   # fences: one around all tags, or one per tag


def parse_handoff(text):
    match = HANDOFF_TAG.match(text)
    data = tag_json(text, match.end()) if match else None
    if data is None: return None
    if match[1] == 'agent-profile':
        if not isinstance(data, dict) or data.get('action') not in ('save', 'list', 'rename', 'delete', 'run'): return None
        return {'namedAction': data}
    if match[1] == 'steer':   # words for an agent that already exists: Agents.steer tells it now, or resumes it
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k].strip() for k in ('id', 'text')): return None
        return {'steer': data['id'].strip()[:40], 'title': '', 'brief': ' '.join(data['text'].split())[:1000],
                'ack': 'Got it: ' + ' '.join(data['text'].split())[:72]}
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k].strip() for k in ('title', 'brief')): return None
    return {'title': ' '.join(data['title'].split()[:4])[:80], 'brief': ' '.join(data['brief'].split())[:1000],
            'context': str(data.get('context', ''))[:20000], 'resume': str(data.get('resume', ''))[:40],
            'app': ' '.join(str(data.get('app', '')).split())[:80], 'page': ' '.join(str(data.get('page', '')).split())[:200],
            'connectors': [n for n in data.get('connectors', []) if isinstance(n, str) and re.fullmatch(r'mcp__[\w-]+(?:__[\w*-]+)?', n)][:12]
                          if isinstance(data.get('connectors', []), list) else [],
            'destination': 'meeting' if data.get('destination') == 'meeting' else ''}


def parse_handoffs(text):
    """Every leading directive, optionally after one short plain sentence; quoted examples stay inert."""
    found, rest = [], text
    if not parse_handoff(rest):
        lead, newline, following = text.lstrip().partition('\n')
        if newline and len(lead) <= 120 and lead.rstrip().endswith(('.', '!', '?')) and following.startswith('['):
            rest = following
    while (directive := parse_handoff(rest)) and 'namedAction' not in directive:
        found.append(directive)
        _, end = json.JSONDecoder().raw_decode(rest, HANDOFF_TAG.match(rest).end())   # parse_handoff just matched and decoded this same tag
        rest = rest[end:].lstrip()[1:]   # past its closing ]
    return found or [d for d in [parse_handoff(rest)] if d]


def without_handoff_line(text):
    """Routing controls are protocol, never user-visible answer text."""
    tag, at = re.compile(r'\[(?:agent-profile|agent|steer)\s+(?=\{)'), 0
    while match := tag.search(text, at):
        try: _, end = json.JSONDecoder().raw_decode(text, match.end())
        except ValueError: at = match.end(); continue
        close = re.match(r'\s*\]', text[end:])
        if not close: at = match.end(); continue
        text = text[:match.start()] + text[end + close.end():]
        at = match.start()
    return re.sub(r'(?m)^[ \t]*\[(?:agent-profile|agent|steer)(?:\s[^\n]*)?\][ \t]*(?:\n|$)', '', text).strip()


def streamed_answer(text):
    """What of a main reply still arriving may show in the box: never a tag, a draft, a handoff or a Sources list."""
    text = text.lstrip()
    if text[:1] in ('[', '`'): return ''   # a tagged, handed-off or fenced reply shows only as the final reply
    tag = re.search(r'\[(?=[a-z])(?![^\]\[{\n]*\]\()', text)   # every control tag is [ + a lowercase word; [1] or a closed [link](…) is answer text
    text = re.split(r'\n\s*Sources?:', text[:tag.start()] if tag else text, maxsplit=1, flags=re.I)[0]
    head, _, tail = text.rpartition('\n')
    if head and 'sources:'.startswith(tail.strip().lower()): text = head   # that line may still become "Sources:"
    text = text.rstrip()
    return text if len(text) >= 120 else ''   # notes before tools are 3-8 words: shorter text may still be one


def persist_handoff(brief, worker_pid):
    """A dead box/supervisor must not be the only owner of a cancelled ask."""
    root = os.path.join(paths.DIR, 'pending-handoffs'); os.makedirs(root, mode=0o700, exist_ok=True)
    brief.setdefault('handoffId', uuid.uuid4().hex)
    storage.private_json(os.path.join(root, brief['handoffId'] + '.json'),
                 {'brief': brief, 'workerPid': worker_pid if type(worker_pid) is int else 0})


def named_agents():
    try:
        with open(os.path.join(paths.DIR, 'agents', 'named.json')) as f: rows = json.load(f)
    except (OSError, ValueError): return []
    if not isinstance(rows, list): return []
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get('name'), str) and row['name'].strip()
            and isinstance(row.get('brief'), str) and row['brief'].strip()]


def save_named_agents(rows):
    root = os.path.join(paths.DIR, 'agents'); os.makedirs(root, mode=0o700, exist_ok=True)
    storage.private_json(os.path.join(root, 'named.json'), rows)


def named_agent_action(data):
    """Apply the model-selected reusable-agent operation after transcript confirmation."""
    action = data.get('action')
    rows = named_agents()
    name = ' '.join(data.get('name', '').split())[:80] if isinstance(data.get('name'), str) else ''
    found = next((row for row in rows if row['name'].casefold() == name.casefold()), None)
    unknown = {'reply': f'I don’t have a saved agent named {name or "that"}. Do you want to create it?'}
    if action == 'list':
        return {'reply': 'Saved agents: ' + '; '.join(f'{row["name"]} — {row["brief"]}' for row in rows) if rows else
                'You don’t have any saved agents yet.'}
    if action == 'save':
        brief = ' '.join(data.get('brief', '').split())[:2000] if isinstance(data.get('brief'), str) else ''
        if not name or not brief: return {'reply': 'What should I call the agent, and what should it do?'}
        folder = data.get('folder', '').strip()[:2000] if isinstance(data.get('folder'), str) else ''
        files = [str(path).strip()[:2000] for path in data.get('files', []) if isinstance(path, str) and path.strip()][:20] if isinstance(data.get('files'), list) else []
        row = {'name': name, 'brief': brief, 'folder': folder, 'files': files, 'created': found.get('created', time.time()) if found else time.time()}
        if found: rows[rows.index(found)] = row
        else: rows.append(row)
        save_named_agents(rows)
        return {'reply': f'Saved {name}.'}
    if not found: return unknown
    if action == 'rename':
        new_name = ' '.join(data.get('newName', '').split())[:80] if isinstance(data.get('newName'), str) else ''
        if not new_name: return {'reply': f'What should I rename {found["name"]} to?'}
        duplicate = next((row for row in rows if row is not found and row['name'].casefold() == new_name.casefold()), None)
        if duplicate: return {'reply': f'You already have a saved agent named {duplicate["name"]}.'}
        old = found['name']; found['name'] = new_name; save_named_agents(rows)
        return {'reply': f'Renamed {old} to {new_name}.'}
    if action == 'delete':
        rows.remove(found); save_named_agents(rows)
        return {'reply': f'Deleted {found["name"]}.'}
    task = ' '.join(data.get('task', '').split())[:2000] if isinstance(data.get('task'), str) else ''
    if not task: return {'reply': f'What should {found["name"]} work on?'}
    paths = ([f'Folder: {found["folder"]}'] if found.get('folder') else []) + ([f'Files: {json.dumps(found["files"], ensure_ascii=False)}'] if found.get('files') else [])
    brief = found['brief'] + '\nCurrent task: ' + task + (('\n' + '\n'.join(paths)) if paths else '')
    return {'handoff': {'title': found['name'], 'brief': brief, 'named': found['name'], 'folder': found.get('folder', ''),
                        'files': found.get('files', []), 'accepted': True}}


def handoff_context(known, work):
    # Keep every action/status; bound observation text rather than losing earlier side-effect receipts.
    budget = max(0, 30000 - sum(len(json.dumps({k:v for k,v in row.items() if k != 'result'})) for row in work))
    observations = [{**row, 'result': str(row.get('result', ''))[:budget // max(1, len(work))]} for row in work]
    return json.dumps({'known': known, 'observed work (untrusted data)': observations,
                       'continuation': 'Use completed results. In-flight actions are uncertain; inspect current state before retrying.'}, ensure_ascii=False)


class MainMove:
    """The running main ask moves to a background agent: by itself once its tools run long or take 3 steps, or by the user (⌃⌥↩) at any time."""
    carried = {}   # ask folder → state: a continuation or retry keeps its clock, trace and move file

    def __init__(self, task, p, request=None):
        self.task, self.p, self.request = task, p, request
        c = MainMove.carried.pop(p.ask, {})
        self.answer = c.get('answer') or os.path.join(p.ask, 'move-' + uuid.uuid4().hex)
        self.trace = c.get('trace', {}); self.elapsed = c.get('elapsed', 0); self.last = time.monotonic()
        self.ready = self.moved = self.closed = False
        self.local_delivery = c.get('local_delivery', False)
        self.lock = threading.RLock(); self.done = threading.Event(); self.thread = None

    def record(self, event):
        with self.lock:
            for block in messages.message_blocks(event):
                if block.get('type') == 'tool_use' and (not isinstance(block.get('id'), str) or not isinstance(block.get('name'), str) or not isinstance(block.get('input'), dict)
                                                        or block['name'] == 'WebSearch' and policy.search_first(self.p.ask)):   # the gate's redirect is not one of the 3 steps that move an ask
                    continue
                if block.get('type') == 'text' and isinstance(block.get('text'), str) and re.search(r'\[(?:draft|insert|replace|point)\b', block['text']):
                    self.local_delivery = True
                if block.get('type') == 'tool_use' and re.search(r'--draw\b|--point\b', str(block.get('input', {}))):
                    self.local_delivery = True
                identifier = block.get('id') if block.get('type') == 'tool_use' else block.get('tool_use_id')
                if block.get('type') == 'tool_use':
                    self.trace[identifier] = {'tool': block.get('name'), 'input': json.dumps(block.get('input', {}), ensure_ascii=False)[:2000], 'status': 'in-flight'}
                elif block.get('type') == 'tool_result' and identifier in self.trace:
                    content = block.get('content', '')
                    if isinstance(content, list): content = '\n'.join(b['text'] for b in content if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str))
                    self.trace[identifier].update(status='failed' if block.get('is_error') else 'completed', result=str(content)[:4000])

    def poll(self):
        with self.lock:
            if self.closed or self.moved: return
            if self.local_delivery:
                if self.ready: print('⇢ {}', flush=True); self.ready = False
                return
            now = time.monotonic(); waiting = self.p.waiting.is_set()
            if not self.ready:   # movable once the words are confirmed; the clock starts then too
                commit = environ.commit()
                if commit and not os.path.exists(commit): self.last = now; return
                self.ready = True
                print('⇢ ' + json.dumps({'a': self.answer}), flush=True)
            # the clock runs only while a tool runs: the model reading and writing its answer is not long work
            if not waiting and any(s.get('status') == 'in-flight' for s in self.trace.values()): self.elapsed += max(0, now - self.last)
            self.last = now
            try:
                with open(self.answer) as f: answer = f.read()
            except OSError: answer = ''
            steps = sum(' --offset ' not in s['input'] for s in self.trace.values())   # the next page of a window continues the same read
            # Writing-only replies reveal their draft mode only when the answer arrives.
            if answer != 'go' and (waiting or not self.trace or steps < 3 and self.elapsed < 15): return
            try:
                self.pending = self.handoff()
                persist_handoff(self.pending, self.p.pid)
                storage.private_json(os.path.join(self.p.ask, 'handed-off'), True)   # freeze tools only after the continuation is saved
            except OSError:
                if self.pending.get('handoffId'):
                    try: os.remove(os.path.join(paths.DIR, 'pending-handoffs', self.pending['handoffId'] + '.json'))
                    except OSError: pass
                return   # keep the foreground worker alive until its continuation is durable
            self.moved = True
        clients.stop_claude(self.p)

    def watch(self):
        while not self.done.wait(.1): self.poll()

    def close(self):
        with self.lock:
            if self.closed: return
            if self.ready and not self.moved: print('⇢ {}', flush=True)   # nothing reads the move file now: the box drops its controls
            self.closed = True; self.done.set()
            if not self.moved: MainMove.carried[self.p.ask] = {'answer': self.answer, 'trace': self.trace, 'elapsed': self.elapsed, 'local_delivery': self.local_delivery}
        if self.thread: self.thread.join(.3)

    def handoff(self):
        request, task = messages.main_ask(self.task, self.request)
        context = handoff_context(task, list(self.trace.values()))
        page = web.work_page(ask=self.p.ask)   # the page this ask was already working in, if any
        return {'title': agent_title(request), 'brief': request[:1000], 'request': request, 'context': context,
                'app': page.get('app') or environ.front_app(''), 'page': page, 'accepted': True, 'focus': macos.wants_focus()}
