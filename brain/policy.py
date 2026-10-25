"""The safety gate: what the user must OK first (risky), the tool hook (gate), "Always allow for this task", and the
background agents' URL allowlist. One source for what may run without asking."""
import fcntl
import json
import os
import re
import shlex
import sys
import time
import urllib.parse
from collections import Counter
from brain import environ, interaction, labels, macos, paths, prefs, storage

__all__ = ['DENIED', 'DENY', 'SAFE_OUT', 'RISKY', 'REDIRECT', 'SCRIPT_RUNNERS', 'FILE_CHANGERS', 'SYSTEM_CHANGERS',
           'GIT_DESTROYS', 'WRAPPERS', 'RISKY_LABEL', 'RUNS', 'APP_DIRS', 'QUIET', 'ARRANGE', 'launches_program', 'runs_path',
           'risky', 'runs_helper', 'simple_commands', 'shell_tokens', 'focus_command', 'recursive_ask', 'search_first', 'gate',
           'action_kind', 'task_allowed', 'allow_for_task', 'managed_agent', 'agent_url_parts', 'agent_url_observe',
           'agent_url_allowed', 'agent_url_denial', 'agent_sources', 'agent_read_command', 'connector_annotations']


# Full access: everything runs without asking, except these, which a misheard word must never trigger.
DENIED = ('rm', 'rmdir', 'sudo', 'dd', 'diskutil', 'shutdown', 'reboot', 'halt', 'git push', 'srm')


DENY = [f'Bash({c}:*)' for c in DENIED]


# Safe mode (Settings, on by default): the gate checks every command, and main asks and background agents run in Claude Code's
# sandbox, which writes only to their working folder. These run outside it, so Rabik's helpers open apps and sites normally.
# A chain runs outside only if every part is listed, so harmless read-only tools are too ("…; curl wttr.in", "| head").
SAFE_OUT = [f'{c} *' for c in ('osascript', 'open', 'mdfind', 'curl', 'head', 'tail', 'grep', 'sort', 'wc', 'echo', 'sleep', 'date', paths.ME)] + ['pbpaste', 'date'] + [f'orca terminal {c} *' for c in ('list', 'read', 'send')]


# What the user must OK first. Matched per command, so `open "…?q=buy shoes"` or a search for "delete" never asks.
RISKY = [('Delete something?', r'\b(rm|rmdir|srm|unlink|shred|trash|mv)\s|\bdelete\b|empty (the )?trash'),
         ('Send this?', r'\bsend\b|\bsendmail\b|curl\b.*\s((?-i:-[a-zA-Z]*X)\s*[\'"]?(POST|PUT|PATCH|DELETE)|--request[\s=]*[\'"]?(POST|PUT|PATCH|DELETE)|--data|--form|--json|--upload-file|(?-i:-[a-zA-Z]*[dFT]))'),
         ('Buy this?', r'\b(buy|purchase|checkout|check out|place (an |the )?order|pay)\b'),
         # every way curl, sort and AppleScript/JXA write a file: they run outside the sandbox
         ('Change a file?', r'\btee\s|curl\b.*\s((?-i:-[a-zA-Z]*[oODcK])|--(output|remote-name|dump-header|cookie-jar|trace|stderr|libcurl|etag-save|hsts|alt-svc|config)\b)|%output\{'
                            r'|\bsort\b.*\s((?-i:-[a-zA-Z]*o)|--output)|\bwrite\b.*\bto\b|write permission|writeTo(File|URL)'),
         # AppleScript and JXA can run shell text: Terminal's do script, do shell script, run/load script, ObjC tasks
         ('Run a system command?', r'\bdo ?(shell ?)?script\b|\b(run|load) ?script\b|\bNSTask\b|\$\.(system|popen)\b|\bsudo\b|\bkillall\b|\bdefaults write\b')]


# A redirect that writes a file; not one to /dev/null, to a file descriptor (2>&1, >&2) or into the scratch /tmp.
REDIRECT = r'(?<!&)>>?\|?\s*(?!/dev/(?:null|stdout|stderr)\b|&|(?:/private)?/tmp/(?!\S*\.\.))\S'


# Programs judged by their command position, never by words in their arguments (a search for "install python" runs nothing).
SCRIPT_RUNNERS = re.compile(r'python[\d.]*|perl[\d.]*|ruby|node(?:js)?|deno|bun|php|lua|tclsh|swift|(?:ba|da|z|k|c|tc|fi)?sh|eval|source|\.')


FILE_CHANGERS = {'truncate', 'cp', 'ditto', 'rsync', 'install', 'ln', 'chmod', 'chown', 'chgrp', 'chflags', 'xattr', 'touch', 'mkfile',
                 'wget', 'patch', 'tar', 'unzip', 'zip', 'gzip', 'gunzip', 'bzip2', 'xz'}


SYSTEM_CHANGERS = {'kill', 'pkill', 'launchctl', 'networksetup', 'scutil', 'pmset', 'systemsetup', 'tmutil', 'spctl', 'csrutil', 'nvram', 'profiles', 'dscl'}


GIT_DESTROYS = re.compile(r'clean|reset --hard|checkout --|restore|stash (?:drop|clear)|branch -D')


WRAPPERS = {'env': ('-u', '-S', '-P'), 'command': (), 'nohup': (), 'exec': ('-a',), 'xargs': ('-I', '-J', '-L', '-n', '-P', '-E', '-s'),
            'time': (), 'nice': ('-n',), 'timeout': ('-s', '-k'), 'builtin': (), 'caffeinate': ('-t', '-w')}


# Hands.riskyPattern (Sources/Rabik/Hands/Hands.swift): a raw System Events click asks for the same controls --hands does
RISKY_LABEL = r"(?i)\b(buy|purchase|pay|payment|checkout|order|send|delete|remove|trash|submit|publish|post|sign.?out|log.?out|unsubscribe|subscribe|transfer|bid|erase|withdraw|donate|authorize|grant access|allow access|logout|book|reserve|merge|deploy|discard|wipe|format|apply(?! filters| changes| settings| coupon| code| promo| discount| theme| style| formatting)|confirm)\b"


RUNS = ('.command', '.tool', '.terminal', '.sh', '.zsh', '.bash', '.app', '.workflow', '.action')   # macOS runs these when opened


APP_DIRS = ('/Applications/', '/System/Applications/', os.path.join(paths.HOME, 'Applications') + '/')


QUIET = (paths.DRAW, paths.SEARCH, paths.READ, paths.LOOK, paths.FRONT, paths.SHOW, paths.PLACE, paths.PLAY, paths.QUEUE, paths.TYPE, paths.REMEMBER, paths.FORGET, paths.ABOUT, paths.PICK, paths.SET, paths.WEB, paths.HISTORY, paths.HANDS, paths.WINDOW, f'{shlex.quote(paths.ME)} --calendar ', 'open ', 'mdfind ', 'pbpaste')   # helpers confirm their own risky actions


def launches_program(part):
    """`open` or --show of a script, program or app outside the Applications folders: macOS runs it, outside the sandbox.
    A path that does not exist yet counts too: this same command makes it, so the gate cannot see what it is."""
    try: tokens = shlex.split(part)
    except ValueError: return False
    named = lambda t: '/' not in t and not t.startswith('~')   # "Notes": an installed app by name, not a path
    if tokens[1:2] == ['--show'] and (os.path.basename(tokens[0]) == 'rabik.py' or tokens[0].startswith('$')): targets = [t for t in tokens[2:] if t != '--bg' and not (named(t) and not os.path.exists(t))]
    elif tokens and os.path.basename(tokens[0]) == 'open':
        targets, rest = [], iter(tokens[1:])
        for t in rest:
            if t == '--args': break
            if t in ('-a', '-b', '-s', '-u', '--env', '--stdin', '--stdout', '--stderr', '--arch'):
                value = next(rest, '')
                if t == '-a' and not named(value): targets.append(value)
            elif not t.startswith('-'): targets.append(t)
    else: return False
    return any(map(runs_path, targets))


def runs_path(t):
    if re.match(r'[a-z][\w+.-]*:', t, re.I) and not t.lower().startswith('file:'): return False   # a web or settings link
    path = os.path.abspath(os.path.expanduser(urllib.parse.unquote(re.sub(r'^file://', '', t, flags=re.I))))
    return not os.path.exists(path) or path.lower().endswith(RUNS) and not (path.endswith('.app') and path.startswith(APP_DIRS)) or os.path.isfile(path) and os.access(path, os.X_OK)


def risky(cmd):
    """-> the question to ask the user, or '' when the command can just run."""
    # Both splits: the quoted one keeps `write "a|b" to file` whole; the plain one still sees past \" and $'…' quoting.
    for part in re.split(r'[;&|\n]', cmd) + re.findall(r'(?:\\.|"(?:[^"\\]|\\.)*"|\'[^\']*\'|[^;&|\n])+', cmd):
        part = part.strip()
        if launches_program(part): return 'Run a program?'
        if re.search(r'(?:^|[\s/])osascript(?:\s|$)', part) and not re.search(r'\s-e\s', part) and '<<' not in cmd:
            return 'Run a script?'   # from a file or a pipe: the gate cannot read what it does
        if re.search(REDIRECT, re.sub(r'"[^"$`]*"|\'[^\']*\'', '""', part)):   # before the quiet helpers: `pbpaste > file` writes one
            return 'Change a file?'
        if part.startswith(QUIET) and '$(' not in part and '`' not in part:
            continue
        for q, rx in RISKY:
            if re.search(rx, re.sub(r'"[^"$`]*"', '""', part) if q == 'Change a file?' else part, re.I):   # "View > Zoom" menu paths are not redirects
                return q
        if 'osascript' in part and (re.search(r'\b(open|launch|run)', re.sub(r'"[^"]*"', '""', part), re.I) or re.search(r'application\s+"(/|~|file:)', part, re.I)) \
                and any(map(runs_path, re.findall(r'"((?:/|~|file:)[^"]*)"', part))):
            return 'Run a program?'   # Finder or an app opening a script, program or not-yet-made path
        if 'osascript' in part and re.search(r'\bclick\b|perform action', part, re.I) and (re.search(r'\bclick at\b', part, re.I) or any(
                re.search(RISKY_LABEL, s) or re.fullmatch(r'(?i)\s*(ok|yes|continue|allow|accept|agree|complete|finish|grant)\s*', s) for s in re.findall(r'"([^"]*)"', part))):
            return 'Click this?'   # what --hands asks for too: a blind screen point, or a control that sends, buys, deletes or confirms
        if 'osascript' in part and re.search(r'(keystroke\s+(return|enter|"[qwd]")|key code\s+(36|76|51|117|12|13|2|53))\s+using\s+(\{[^}]*)?command down', part, re.I):
            return 'Press this key?'   # ⌘Return sends, ⌘Delete deletes, ⌘Q/⌘W close without asking
    argvs = simple_commands(cmd)
    if argvs is None: return 'Run a script?'   # quoting the gate cannot read cannot be vouched for
    for argv in argvs:
        name, args = os.path.basename(argv[0]), argv[1:]
        if SCRIPT_RUNNERS.fullmatch(name) and not runs_helper(args):
            return 'Run a script?'   # inline or file code (python3 -c, sh -c, node x.js) can do anything; only this helper is known
        if name in FILE_CHANGERS or name == 'sed' and any(a.startswith(('-i', '--in-place')) for a in args) or \
                name == 'plutil' and any(a in ('-convert', '-insert', '-replace', '-remove', '-o') for a in args):
            return 'Change a file?'
        if name == 'git' and GIT_DESTROYS.match(' '.join(args)):
            return 'Delete something?'
        if name in SYSTEM_CHANGERS:
            return 'Run a system command?'
    return ''


def runs_helper(args):
    """An interpreter's arguments run this helper file (python3 rabik.py --place …, sh rabik.py …), not code of its own."""
    script = next((a for a in args if not a.startswith('-')), '')
    return bool(script) and not any(a.startswith('-') for a in args[:args.index(script)]) and \
        os.path.realpath(os.path.expanduser(script)) == os.path.realpath(paths.ME)


def simple_commands(cmd):
    """Each simple command's words in a shell line, inside $(…), `…`, ( … ) and find -exec too, past VAR=value prefixes,
    wrappers (env, nohup, xargs…) and $VAR aliases set earlier in the line. None when its quoting cannot be read."""
    try: tokens = shell_tokens(cmd.replace('`', ' ; '))   # a backquote opens or closes a command: either way a boundary
    except ValueError: return None
    commands, current, nested = [], [], []
    for token in tokens + [';']:
        if '$(' in token or ' ; ' in token: nested.append(token.split('$(', 1)[-1])   # a substitution kept inside "…" still runs
        if token in (';', '&&', '||', '|', '|&', '&', '(', ')', '-exec', '-execdir', '-ok', '-okdir') or token == '$' and not current:
            if current: commands.append(current)
            current = []
        elif token not in ('<', '>', '<<', '>>', '>&', '<&', '&>', '>|') or not current:
            current.append(token)
    out, aliases = [], {}
    for argv in commands:
        argv = [t for t in argv if t != '$']
        while argv and re.fullmatch(r'[A-Za-z_]\w*=.*', argv[0]):
            name, _, value = argv[0].partition('='); aliases[name] = value; argv = argv[1:]
        argv = [aliases.get(next(filter(None, m.groups())), t) if (m := re.fullmatch(r'\$(\w+)|\$\{(\w+)\}', t)) else t for t in argv]
        while argv and os.path.basename(argv[0]) in WRAPPERS:
            takes, argv = WRAPPERS[os.path.basename(argv[0])], argv[1:]
            while argv and (argv[0].startswith('-') or re.fullmatch(r'[A-Za-z_]\w*=.*|\d+[smhd]?', argv[0])):
                argv = argv[2:] if argv[0] in takes else argv[1:]
        if argv: out.append(argv)
    for text in nested:
        inner = simple_commands(text)
        if inner is None: return None
        out += inner
    return out


def shell_tokens(cmd):
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars='();<>|&\n')
    lexer.whitespace = ' \t\r'; lexer.whitespace_split = True; lexer.commenters = ''
    return [';' if token and not token.strip('\n') else token for token in lexer]


def focus_command(cmd):
    try: tokens = shell_tokens(cmd)
    except ValueError: return True
    for i, token in enumerate(tokens):
        if os.path.basename(token) == 'open':
            boundary = max((j for j in range(i) if tokens[j] in (';', '&&', '||', '|')), default=-1)
            head = tokens[boundary + 1:i]
            if (not head or os.path.basename(head[0]) in ('env', 'command', 'nohup', 'exec', 'xargs')) and '-g' not in tokens[i + 1:next((j for j in range(i + 1, len(tokens)) if tokens[j] in (';', '&&', '||', '|')), len(tokens))]: return True
        if os.path.basename(token) == 'osascript':
            script = ' '.join(tokens[i + 1:])
            if re.search(r'perform action\s+"AXRaise"', script, re.I) or re.search(r'\bactivate\b|set\s+frontmost\b.*\btrue\b', re.sub(r'"(?:[^"\\]|\\.)*"', '""', script), re.I): return True
    return False


def recursive_ask(tokens):
    aliases = {}
    for i, token in enumerate(tokens):
        assignment = re.fullmatch(r'([A-Za-z_]\w*)=(.*)', token)
        if assignment:
            aliases[assignment[1]] = assignment[2]
            continue
        variable = re.fullmatch(r'\$(\w+)|\$\{(\w+)\}', token)
        executable = aliases.get(next(filter(None, variable.groups()), ''), token) if variable else token
        if os.path.basename(executable) != 'rabik.py': continue
        boundary = max((j for j in range(i) if tokens[j] in (';', '&&', '||', '|')), default=-1)
        head = tokens[boundary + 1:i]
        invoked = not head or re.fullmatch(r'python(?:3(?:\.\d+)?)?|(?:ba|da|z)?sh', os.path.basename(head[-1])) or token == paths.ME and os.path.basename(head[0]) in ('env', 'command', 'nohup', 'exec', 'xargs')
        if invoked and (i + 1 == len(tokens) or not tokens[i + 1].startswith('--') or tokens[i + 1] in ('--wait', '--plan')): return True
    return False


def search_first(ask):
    """A main ask's WebSearch is turned back to the free --search until that has run in this ask: a redirect, not a failed step."""
    return bool(ask) and not os.path.exists(os.path.join(ask, 'searched'))


def gate():
    """AI client's PreToolUse hook: native hands cannot bypass their wrapper; in safe mode a risky command waits for the user's Allow (60 s, then no).
    A main ask's command the user allowed runs for real, outside the sandbox; an agent's stays in unless it asked to leave.
    The AI asking to leave the sandbox by itself asks too."""
    external = environ.client_override() in ('devin', 'pi')
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or not isinstance(event.get('tool_input', {}), dict): raise ValueError('Invalid tool event')
        inp = event.get('tool_input', {})
        if 'command' in inp and not isinstance(inp['command'], str): raise ValueError('Invalid command')
    except (ValueError, TypeError):
        print(json.dumps({'decision':'block','reason':'Invalid tool event.'} if external else {'hookSpecificOutput':
              {'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':'Invalid tool event.'}}))
        if external: sys.exit(2)
        return

    external_tool = ''
    if external and isinstance(event.get('tool_name'), str):
        external_tool = {'fetch': 'webfetch'}.get(event['tool_name'].casefold(), event['tool_name'].casefold())
    trusted_read = event.get('tool_name') == 'Bash' and agent_read_command(inp.get('command', ''), event.get('cwd'))
    def decision(ok, reason):
        if external:
            print(json.dumps({'decision': 'approve' if ok else 'block', 'reason': reason}))
        else:
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                              'permissionDecision': 'allow' if ok else 'deny',
                              **({'updatedInput': {**inp, **({'command': trusted_read} if trusted_read else {}), 'dangerouslyDisableSandbox': True}} if ok and event.get('tool_name') == 'Bash' and
                                 (not environ.agent() or inp.get('dangerouslyDisableSandbox') or trusted_read) else
                                 {'permissionDecisionReason': reason} if not ok else {})}}))
    def record_external():
        if not external or not environ.ask_dir(): return
        step = labels.label('Bash' if external_tool == 'exec' else external_tool, inp)
        source = environ.client_override('client')
        with open(os.path.join(environ.ask_dir(required=True), source + '-tools.jsonl'), 'a') as f:
            f.write(json.dumps({'tool': external_tool, 'input': inp, 'step': step}) + '\n')
        tmp = os.path.join(environ.ask_dir(required=True), f'.hands-{source}-{time.time_ns()}')
        with open(tmp, 'w') as f:
            f.write('▸ ' + step)
        os.rename(tmp, tmp.replace('/.hands-', '/hands-'))

    if not interaction.wait_commit():
        decision(False, 'The request was cancelled before the transcript was confirmed.')
        return
    if os.path.exists(os.path.join(environ.ask_dir(paths.DIR), 'handed-off')):
        decision(False, 'This request was handed off. Its tools belong to the background agent.'); return
    if event.get('tool_name') == 'WebFetch' and not agent_url_allowed(inp.get('url', '')):
        decision(False, agent_url_denial()); return
    # WebSearch takes 4-6 s and is billed per search; the free helper takes ~2 s. The prompt's "on failure" alone was ignored.
    if event.get('tool_name') == 'WebSearch' and not external and search_first(environ.ask_dir()):
        decision(False, f'Run {paths.SEARCH} "<query>" first; WebSearch only if it fails or misses.'); return
    if environ.agent() and event.get('tool_name') == 'Bash' and re.search(r'(?:^|[\s;&|(/])open\s[^;&|]*https?://', inp.get('command', '')):
        decision(False, f'Open web pages with {paths.ME} --web read "<url>": it uses this task\'s own browser window, never the user\'s tabs.'); return
    agent_approved = False
    if event.get('tool_name', '').startswith('mcp__') and (prefs.pref('safe', True) or environ.agent_prep()):
        annotations = connector_annotations(event, environ.ask_dir(''))
        if annotations.get('readOnly', annotations.get('readOnlyHint')) is True and not annotations.get('destructive', annotations.get('destructiveHint', False)):
            decision(True, '')
            return
        if environ.agent_prep():
            decision(False, 'Call preparation is read-only. This tool is not annotated read-only.')
            return
        directory = environ.ask_dir()
        if not directory:
            decision(False, 'Safe mode: connector metadata is missing; approval is required.')
            return
        kind = event['tool_name']
        answer = 'y' if task_allowed(kind) else interaction.ask_user({'q': 'Allow this connector action?',
                         'cmd': event['tool_name'] + '\n' + json.dumps(inp, ensure_ascii=False)[:800], 'task': True}, 600)
        if answer == 'task': allow_for_task(kind)
        decision(answer in ('y', 'task'), 'The user said no. Do not try another way.')
        return
    if environ.agent() and prefs.pref('safe', True) and event.get('tool_name') in ('Bash', 'Write', 'Edit') and not trusted_read:
        kind = action_kind(event['tool_name'], inp)
        answer = 'y' if task_allowed(kind) else interaction.ask_user(
            {'q': 'Allow this task action?', 'cmd': (str(inp.get('file_path', '')) + '\n' + json.dumps(inp, ensure_ascii=False)).strip()[:800], 'task': bool(kind)}, 600)
        if answer == 'task': allow_for_task(kind)
        if answer not in ('y', 'task'):
            decision(False, 'The user said no. Do not try another way.'); return
        agent_approved = True
        # Keep the shared command validations below: approval never bypasses Rabik's hard denials.
    if external and external_tool not in ('read', 'grep', 'glob', 'exec', 'webfetch'):
        decision(False, 'This tool is disabled by Rabik.')
        return
    cmd = inp.get('command', '')
    try: tokens = shell_tokens(cmd)
    except ValueError:
        decision(False, 'The command has incomplete quoting. Please correct it and try again.'); return
    if external and cmd:
        words = [os.path.basename(x) for x in re.findall(r'[\w./-]+', cmd + ' ' + ' '.join(tokens))]
        denied = any(x in DENIED for x in words) or 'git' in words and 'push' in words[words.index('git') + 1:]
        if denied:
            decision(False, 'Rabik always blocks this command.'); return
    if len(tokens) > 2 and os.path.basename(tokens[0]) == 'open' and os.path.basename(tokens[1]) == 'rabik.py' and tokens[2].startswith('--'):
        decision(False, 'Run the helper directly; do not pass helper commands to open.')
        return
    recursive = recursive_ask(tokens)
    if ARRANGE.search(cmd): macos.free_focus()
    if recursive or focus_command(cmd) and not macos.wants_focus() and prefs.pref('workIn', 'back') != 'front':
        decision(False, 'Tools cannot start another ask.' if recursive else 'Work in the background. Use --show --bg or hands; focus only when asked.')
        return
    if (re.search(r'RABIK_HANDS_RECEIPT|RABIK_\w+\s*=|--hands\s+label\b|--recap\s+remind\b', cmd) or   # Reminders get only what the user picks
        '--hands' in cmd and (paths.APP in cmd or 'RABIK_APP' in cmd or re.search(r'(?:^|[/\s\"\'])Rabik(?:-real)?(?:[\s\"\']|$)', cmd)) or
        '--calendar' in tokens and any(t == paths.APP or os.path.basename(t) in ('Rabik', 'Rabik-real') for t in tokens[:tokens.index('--calendar')])):
        decision(False, 'Use rabik.py --hands or --calendar; native actions and safety overrides are not model tools.')
        return
    q = '' if agent_approved or trusted_read else risky(cmd) or ('Run outside the safe folder?' if inp.get('dangerouslyDisableSandbox') or external and cmd else '')
    if not q or not environ.ask_dir() or not prefs.pref('safe', True):
        if environ.ask_dir(): macos.preview_commands(cmd)
        record_external()
        if environ.agent() or trusted_read or external: decision(True, '')
        return
    ok = interaction.ask_user({'q': q, 'cmd': cmd[:800]}, 60) == 'y'
    if ok:
        macos.preview_commands(cmd)
        record_external()
    decision(ok, '' if ok else 'The user said no. Do not try another way; say it was not done.')


ARRANGE = re.compile(r'--place\b|AXFullScreen|AXMinimized|\bset (bounds|position|size)\b|\bminiaturized\b', re.I)   # arranging windows is work the user sees


def connector_annotations(event, directory):
    # Metadata comes from the CLI's authenticated mcp_status, never model text or a name heuristic.
    try:
        with open(os.path.join(paths.agent_gate_dir(directory), 'tools.json')) as f: tools = json.load(f)
        value = tools.get(event.get('tool_name'), {})
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError): return {}


def action_kind(tool, inp):
    """What "Always allow for this task" covers: the same tool; for a shell command, the same programs and helper verbs."""
    if tool in ('Write', 'Edit'):   # the folder the card showed: approving a report must not cover ~/.zshrc
        return f"{tool}: {os.path.dirname(os.path.abspath(os.path.expanduser(str(inp.get('file_path', '')))))}"
    if tool != 'Bash': return tool
    command = inp.get('command', '')
    if re.search(r'[$`]|[<>]\(', command): return ''
    try: tokens = shell_tokens(command)
    except ValueError: return ''
    if any(t in ('-exec', '-execdir', '-ok', '-okdir') for t in tokens): return ''
    kinds, start = [], True
    for i, token in enumerate(tokens):
        if token in (';', '&&', '||', '|', '&', '(', ')'): start = True; continue
        if not start or re.fullmatch(r'[A-Za-z_]\w*=.*', token): continue
        start, name = False, os.path.basename(token)
        if name in ('eval', 'env', 'xargs', 'command', 'exec', 'nohup', 'sudo', 'nice', 'time', 'timeout', 'builtin', 'sh', 'bash', 'zsh', 'dash', 'fish'): return ''
        if re.fullmatch(r'python(?:3(?:\.\d+)?)?', name) and i + 1 < len(tokens) and not tokens[i + 1].startswith('-'): start = True; continue   # the script is the program
        if re.fullmatch(r'python(?:3(?:\.\d+)?)?|perl|ruby|node|osascript', name): return ''
        kinds.append(' '.join([name, *tokens[i + 1:i + 3]]) if name == 'rabik.py' else name)
    # an approved `curl <page>` must not cover `curl -T <file>`, nor a sandboxed run one that can write anywhere: each is its own kind
    q = ', '.join(filter(None, [risky(command), 'outside the sandbox' if inp.get('dangerouslyDisableSandbox') else '']))
    return 'Bash: ' + ' + '.join(dict.fromkeys(kinds)) + (f' ({q})' if q else '') if kinds else ''


def task_allowed(kind):
    try:
        with open(os.path.join(paths.agent_gate_dir(environ.ask_dir(required=True)), 'allow-task')) as f: return bool(kind) and kind in json.load(f)
    except (KeyError, OSError, ValueError, TypeError): return False


def allow_for_task(kind):
    if not kind or task_allowed(kind): return
    path = os.path.join(paths.agent_gate_dir(environ.ask_dir(required=True)), 'allow-task')
    try:
        with open(path) as f: kinds = json.load(f)
    except (OSError, ValueError): kinds = []
    storage.private_json(path, (kinds if isinstance(kinds, list) else []) + [kind])


def managed_agent():
    return bool(re.fullmatch(r'[a-f0-9]{32}', environ.agent('')) and environ.ask_dir())


def agent_url_parts(url):
    try:
        page = urllib.parse.urlsplit(url)
        if page.scheme.lower() not in ('http', 'https') or not page.hostname or page.username or page.password: return None
        port = page.port
        host = page.hostname.lower().rstrip('.')
        if ':' in host: host = '[' + host + ']'
        netloc = host + (f':{port}' if port and (page.scheme.lower(), port) not in (('http', 80), ('https', 443)) else '')
        return page.scheme.lower(), netloc, page.path or '/', Counter(urllib.parse.parse_qsl(page.query, keep_blank_values=True))
    except (TypeError, ValueError):
        return None


def agent_url_observe(directory, value):
    """Persist only user/tool-observed URLs outside the agent's writable sandbox."""
    urls = [source['url'] for source in agent_sources(value, 10000)]
    root = paths.agent_gate_dir(directory); os.makedirs(root, mode=0o700, exist_ok=True)
    lock = os.open(os.path.join(root, 'urls.lock'), os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(lock, 'r+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        path = os.path.join(root, 'urls.json')
        try:
            with open(path) as f: old = json.load(f)
        except (OSError, ValueError): old = []
        old = old if isinstance(old, list) else []
        storage.private_json(path, list(dict.fromkeys([u for u in old if isinstance(u, str)] + urls))[:10000])


def agent_url_allowed(url, directory=None):
    """A managed agent may revisit an observed page, optionally after removing query parameters."""
    if not managed_agent(): return True
    wanted = agent_url_parts(url)
    if not wanted: return False
    try:
        with open(os.path.join(paths.agent_gate_dir(directory or environ.ask_dir(required=True)), 'urls.json')) as f: observed = json.load(f)
    except (OSError, ValueError): return False
    for value in observed if isinstance(observed, list) else []:
        known = agent_url_parts(value)
        if known and wanted[:3] == known[:3] and not (wanted[3] - known[3]):
            return True
    return False


def agent_url_denial():
    return ('URL not opened: it was not supplied by the user or observed in an earlier tool result/page. '
            'Search for the site entry page, open the exact result, then use the site search, filter and sort controls.')


def agent_sources(value, most=12):
    sources = {}
    def add(url, title=''):
        try:
            page = urllib.parse.urlsplit(url)
            if page.scheme not in ('http', 'https') or not page.hostname or page.username or page.password: return
            sources[url] = {'url': url[:2000], 'title': ' '.join(str(title or page.hostname).split())[:180], 'domain': page.hostname}
        except ValueError: pass
    def visit(value, depth=0):
        if depth > 6: return
        if isinstance(value, dict):
            if isinstance(value.get('url'), str): add(value['url'], value.get('title', ''))
            for child in list(value.values())[:max(50, most)]: visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value[:max(50, most)]: visit(child, depth + 1)
        elif isinstance(value, str):
            text = value[:1000000 if most > 12 else 40000]
            for title, url in re.findall(r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)', text): add(url, title)
            for line in text.splitlines():
                # Search tools also return JSON source lists inside text blocks.
                start = min((line.find(c) for c in ('[', '{') if c in line), default=-1)
                if start >= 0:
                    try: visit(json.loads(line[start:]), depth + 1)
                    except (ValueError, RecursionError): pass
            for url in re.findall(r'https?://[^\s<>"\'\\\])]+', text):
                url = url.rstrip('.,;')
                if url not in sources: add(url)
    visit(value)
    return list(sources.values())[:most]


def agent_read_command(command, cwd=None):
    # Pin the helper and interpreter; shell spelling must not choose a different runtime.
    if any(c in command for c in ('`', '$', '\n')): return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|<>()'); lexer.whitespace_split = True; lexer.commenters = ''
        args = list(lexer)
    except ValueError: return False
    cwd = cwd or os.getcwd()
    if len(args) > 3 and args[0] == 'cd' and args[2] == '&&':
        cwd = os.path.join(cwd, args[1]); args = args[3:]
    if any(token and all(c in ';&|<>()' for c in token) for token in args): return False
    if args and args[0] in ('python3', sys.executable): args = args[1:]
    try:
        if not args or not os.path.samefile(os.path.join(cwd, args[0]), paths.ME): return False
    except OSError: return False
    if len(args) > 1 and (args[1] in ('--window', '--look', '--read', '--search', '--history', '--meeting-history', '--need') or
                         len(args) > 2 and args[1:3] in (['--hands', 'see'], ['--web', 'read'])):
        return shlex.join(['/bin/sh', paths.ME, *args[1:]])   # the sh header runs it from cached bytecode
    return ''
