"""rabik.py --mcp: Rabik's memory for Claude Code and Claude Desktop, read-only, as an MCP server on stdio (JSON-RPC 2.0, one
message a line, no dependencies). About you and rules, saved meetings, people, goals, daily recaps and Activity history; nothing
can be changed. With AI meeting summaries off, meetings give their title and local recap, never the transcript."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from brain import activity, environ, goals, meeting, memory, paths, people, prefs, recap

__all__ = ['MCP_VERSIONS', 'MCP_TOOLS', 'MCP_CODEX', 'mcp_call', 'mcp_reply', 'mcp_serve', 'mcp_install']


MCP_VERSIONS = ('2025-06-18', '2025-03-26', '2024-11-05')


# The ChatGPT Mac app runs local MCP servers from Codex's config (~/.codex/config.toml) and ships the codex CLI that edits it.
MCP_CODEX = ('/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex', '~/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex')


def _tool(name, title, description, properties=None, required=()):
    return {'name': name, 'title': title, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties or {}, 'required': list(required), 'additionalProperties': False},
            'annotations': {'title': title, 'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}}


_QUERY = {'query': {'type': 'string', 'description': 'Words to look for; a weekday, "today", "yesterday" or a YYYY-MM-DD date also works.'}}
MCP_TOOLS = [
    _tool('search_memory', 'Search Rabik memory', "What Rabik knows about the user (About you facts, saved rules). Empty query lists everything; sensitive facts are never shown.",
          {'query': {'type': 'string', 'description': 'Words to look for, like "Sam" or "address".'}}),
    _tool('list_meetings', 'List saved meetings', 'Saved meetings, newest first: id, date, title, app and the recap\'s first line.',
          {**_QUERY, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'description': 'At most this many (default 10).'}}),
    _tool('read_meeting', 'Read a saved meeting', 'One meeting by id (from list_meetings): recap, action items, notes and the transcript.',
          {'id': {'type': 'string', 'description': 'The meeting id.'}}, required=('id',)),
    _tool('people', 'People', 'People the user met in saved meetings or told Rabik about. With a name: their meetings and what is known; without: everyone.',
          {'name': {'type': 'string', 'description': 'A name, first name or email.'}}),
    _tool('goals', 'Goals', "The user's goals, open and done."),
    _tool('daily_recap', 'Daily recap', "A day's recap: what got done, decisions, to-dos, goals moved, where the time went, tomorrow.",
          {'date': {'type': 'string', 'description': 'YYYY-MM-DD; today by default.'}}),
    _tool('search_activity', 'Search activity history', 'Pages, files and windows the user had in front in the last 30 days (only when Activity history is on).',
          {'query': {'type': 'string', 'description': 'Words, like "pricing figma yesterday".'}}, required=('query',)),
]


def _day_text(day):
    data = recap.recap_read(day)
    if not data: return f'No recap for {day}.'
    lines = [f"Daily recap · {day}", data.get('headline', '')]
    for title, rows in (('Done', data.get('highlights')), ('Decisions', data.get('decisions')),
                        ('To do', [a.get('text', '') for a in data.get('actions') or [] if isinstance(a, dict)]),
                        ('Goals', [f"{g.get('goal')}: {g.get('note')}" for g in data.get('goals') or [] if isinstance(g, dict)]),
                        ('Most time on', data.get('focus')), ('Tomorrow', data.get('tomorrow'))):
        if rows: lines += ['', title + ':'] + ['- ' + str(r) for r in rows]
    return '\n'.join(lines)


def mcp_call(name, args):
    """One tool's text. Raises ValueError for bad arguments."""
    args = args if isinstance(args, dict) else {}
    text = lambda key: str(args.get(key) or '').strip()[:300]
    if name == 'search_memory': return memory.memory_find(text('query'))
    if name == 'list_meetings':
        limit = max(1, min(50, int(args.get('limit') or 10)))
        rows = meeting.meeting_list(text('query'))[:limit]
        return '\n'.join(f"{m['id']} · {datetime.fromtimestamp(m['started']).strftime('%Y-%m-%d %H:%M')} · {m['title']} · {m['app']} · "
                         f"{(m['summary'] or m['status']).splitlines()[0][:200]}" for m in rows) or 'No saved meetings match.'
    if name == 'read_meeting':
        m = meeting.meeting_read(text('id'))
        if not prefs.pref('meetingSummary', True):   # AI meeting summaries off: the transcript stays on this Mac
            return meeting.meeting_recap_text(m) + '\n(The transcript stays on this Mac: AI meeting summaries are off in Rabik.)'
        return meeting.meeting_markdown(m)
    if name == 'people':
        if text('name'): return people.people_find(text('name'))
        rows = people.people_all()
        return '\n'.join(p['name'] + (f" <{p['email']}>" if p['email'] else '') + (f" · last met {datetime.fromtimestamp(p['last']).strftime('%Y-%m-%d')}" if p['last'] else '')
                         for p in rows[:200]) or 'Nobody yet.'
    if name == 'goals':
        rows = goals.goals()
        return '\n'.join(('[done] ' if g.get('done') else '- ') + g['text'] for g in sorted(rows, key=lambda g: bool(g.get('done')))) or 'No goals.'
    if name == 'daily_recap':
        day = text('date') or date.today().isoformat()
        date.fromisoformat(day)   # ValueError for anything else
        return _day_text(day)
    if name == 'search_activity': return activity.activity_search(text('query'))
    raise KeyError(name)


def mcp_reply(message):
    """The answer to one JSON-RPC message, or None for a notification."""
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0': return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
    method, ident, params = message.get('method'), message.get('id'), message.get('params') or {}
    if 'id' not in message: return None   # notifications/initialized, cancelled: nothing to say
    ok = lambda result: {'jsonrpc': '2.0', 'id': ident, 'result': result}
    if method == 'initialize':
        asked = params.get('protocolVersion') if isinstance(params, dict) else None
        return ok({'protocolVersion': asked if asked in MCP_VERSIONS else MCP_VERSIONS[0], 'capabilities': {'tools': {'listChanged': False}},
                   'serverInfo': {'name': 'rabik', 'title': 'Rabik', 'version': paths.APP_VERSION},
                   'instructions': "Read-only access to Rabik, the user's Mac assistant: what it knows about the user, saved meetings, people, "
                                   'goals, daily recaps and (if on) the pages and files they had open. Use it for questions about the user\'s own past.'})
    if method == 'ping': return ok({})
    if method == 'tools/list': return ok({'tools': MCP_TOOLS})
    if method == 'tools/call':
        name = params.get('name') if isinstance(params, dict) else None
        try: return ok({'content': [{'type': 'text', 'text': mcp_call(name, params.get('arguments'))[:60000]}]})
        except KeyError: return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32602, 'message': f'Unknown tool: {name}'}}
        except (OSError, ValueError, TypeError) as e:
            return ok({'content': [{'type': 'text', 'text': f'Could not read that: {e}'}], 'isError': True})
    return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32601, 'message': f'Method not found: {method}'}}


def mcp_serve(inp=None, out=None):
    """Read messages until stdin closes; only JSON-RPC ever goes to stdout."""
    inp, out = inp or sys.stdin, out or sys.stdout
    for line in inp:
        if not line.strip(): continue
        try: message = json.loads(line)
        except ValueError: reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        else: reply = mcp_reply(message)
        if reply is not None: out.write(json.dumps(reply, ensure_ascii=False) + '\n'); out.flush()


def mcp_install(check=False, target='claude'):
    """Settings → Add to Claude Code / Add to ChatGPT, on the user's click, through each app's own CLI (never by editing its
    config): `claude mcp add --scope user rabik -- /bin/sh <rabik.py> --mcp`, or `codex mcp add rabik -- …` for the ChatGPT Mac
    app. check: only whether it is there."""
    if target == 'chatgpt':
        tool = environ.codex() or shutil.which('codex') or next((os.path.expanduser(p) for p in MCP_CODEX if os.path.isfile(os.path.expanduser(p))), None)
        name, add = 'the ChatGPT app', ('add', 'rabik')
        if not tool: return {'target': target, 'added': False, **({} if check else {'error': 'Install the ChatGPT app for Mac first.'})}
    else:
        tool = environ.claude() or shutil.which('claude') or os.path.expanduser('~/.local/bin/claude')
        name, add = 'Claude Code', ('add', '--scope', 'user', 'rabik')
    run = lambda *a: subprocess.run([tool, 'mcp', *a], capture_output=True, text=True, timeout=30, cwd=tempfile.gettempdir(),
                                    env={k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY')})
    try:
        if run('get', 'rabik').returncode == 0: return {'target': target, 'added': True}
        if check: return {'target': target, 'added': False}
        done = run(*add, '--', '/bin/sh', paths.ME, '--mcp')
        return {'target': target, 'added': done.returncode == 0,
                **({} if done.returncode == 0 else {'error': (done.stderr or done.stdout).strip()[:300] or f'{name} could not add it.'})}
    except (OSError, subprocess.TimeoutExpired):
        return {'target': target, 'added': False, 'error': f'{name[0].upper() + name[1:]} is not installed.'}
