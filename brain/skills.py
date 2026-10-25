"""Learned shortcuts and workflows: an action the AI got right, saved as its exact commands and replayed with no AI."""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from brain import apps, environ, hands, macos, memory, paths, policy, prefs, web, windows, wording

__all__ = ['SKILLS', 'INTERNAL_TASK_MARKERS', 'UNSAFE', 'NAMED', 'named_shortcut', 'TRIGGER', 'shortcut_name', 'skills',
           'PLACING', 'LOOKUPS', 'shortcut_commands', 'save_skills', 'learn', 'unlearn', 'app_in', 'like', 'swapped',
           'replay_quit', 'ReplayResult', 'replay', 'outcome', 'workflows', 'replayable', 'remember_workflow']


# Learned shortcuts: an action the AI got right is saved as the exact commands it ran; the same words later replay
# them after confirmation with no AI (free). Kept in a file, never sent to the AI, so they cost nothing as they grow.
SKILLS = os.path.join(paths.DIR, 'skills.json')


INTERNAL_TASK_MARKERS = ('\nAlready completed:', '\nRemaining words:')


# shortcut: a deny list, not proof of safety; shortcuts only ever come from the user's own ask
UNSAFE = re.compile(r'(^|[;&|(`\s])(rm|rmdir|sudo|dd|diskutil|shutdown|reboot|halt|srm|trash|mv|find|curl|wget)\s|git push|\$\(|`|>|\|\s*(ba|z)?sh\b|\bdelete\b|--draw\b')


NAMED = re.compile(r'(?:from now on,? )?when(?:ever)? i say (?:["“\']([^"”\']{2,40})["”\']|([^,:;"“]{2,40}?)\s*(?:[,:;]|\b(?:do|then|can you|please|you)\b))', re.I)   # "When I say work mode, …"


def named_shortcut(text):
    match = NAMED.search(text)
    lead = text[:match.start()] if match else ''   # "No, when I say …" re-teaches it; a longer lead is another instruction
    return match if match and (wording.plain(lead + 'shortcut') == 'shortcut' or len(re.findall(r"[\w']+", lead)) <= 2 and re.search(r'[,.!?]\s*$', lead)) else None


TRIGGER = r'\s*\[shortcut ([^\]\n]{2,40})\]'   # the model names X of "when I say X, do Y"; never shown


def shortcut_name(request, reply):
    """The words a "when I say X, do Y" ask teaches: the code's own split, else the model's [shortcut X] if X is the user's own words
    ("when I say deep work full screen Chrome" has no comma to split at)."""
    named = named_shortcut(request.strip())
    if named: return (named[1] or named[2]).strip()
    tag = re.search(TRIGGER, reply)
    words = lambda text: ' ' + ' '.join(re.findall(r'\w+', wording.plain(text))) + ' '
    return tag[1].strip() if tag and words(tag[1]).strip() and words(tag[1]) in words(request) and words(tag[1]) != words(request) else ''


def skills():
    try:
        with open(SKILLS) as f: saved = json.load(f)
        if not isinstance(saved, dict): return {}
        clean = {task: entry for task, entry in saved.items() if not any(marker.casefold() in task.casefold() for marker in INTERNAL_TASK_MARKERS)
                 and isinstance(entry, dict) and isinstance(entry.get('reply'), str) and isinstance(entry.get('cmds'), list) and all(isinstance(c, str) for c in entry['cmds'])}
        pruned = len(clean) != len(saved)
        saved = clean
        for task, entry in saved.items():
            if not isinstance(entry.get('asked', ''), str): entry.pop('asked')
            commands = shortcut_commands(entry.get('asked') or task, entry['cmds'])
            if commands is not None: entry['cmds'] = commands
        if pruned: save_skills(saved)
        return saved
    except (OSError, ValueError):
        return {}


PLACING = re.compile(r'(?:' + re.escape(shlex.quote(paths.ME)) + r'|\S*rabik\.py) --place ')   # a --place command, its helper path shell-quoted (a checkout path with a space) or not


LOOKUPS = {'mdfind', 'ls', 'grep', 'head', 'tail', 'cat', 'wc', 'sort', 'uniq', 'stat', 'file', 'which'}   # read-only shell tools; find is out (-delete, -exec)


def shortcut_commands(task, commands, app=''):
    """Keep replay actions, with explicit app targets and no discovery or verification reads."""
    result = []
    for command in commands:
        try: tokens = shlex.split(command)
        except (ValueError, TypeError): return None
        if not tokens: continue
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|'); lexer.whitespace_split = True
        parts, flow = [[]], set()
        for t in lexer:
            if t in (';', '&&', '||', '|', '&'): flow.add(t); parts.append([])
            else: parts[-1].append(t)
        if all(p and os.path.basename(p[0]) in LOOKUPS and not any('>' in t and not t.endswith('/dev/null') for t in p) for p in parts): continue   # finding the file (mdfind | head, ls) is discovery too
        if flow - {';', '&&'}: return None   # pipes, fallbacks and background jobs need the AI
        if flow:   # "a; b && c" is a list of actions: each one is checked and replayed on its own, in order
            aliases = {}
            while parts and len(parts[0]) == 1:
                name, sep, value = parts[0][0].partition('=')
                if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name): break
                if value != paths.ME: return None
                aliases[name] = paths.ME; parts.pop(0)
            if aliases:
                for part in parts:
                    for i, token in enumerate(part):
                        match = re.fullmatch(r'\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))', token)
                        if match and (match[1] or match[2]) in aliases:
                            if i not in (0, 1) or i == 1 and part[0] != sys.executable and os.path.basename(part[0]) not in ('python', 'python3'): return None
                            part[i] = aliases[match[1] or match[2]]
                if any('$' in t for p in parts for t in p): return None
            if parts and parts[0] == ['cd', os.path.dirname(paths.ME)]:
                sub = shortcut_commands(task, [shlex.join(p) for p in parts[1:] if p], app)
                if sub is None or not all((t := shlex.split(c))[:1] == [paths.ME] and t[1:2] and t[1] in ('--place', '--hands', '--play', '--queue', '--type') for c in sub): return None
                result += sub; continue   # these actions do not depend on the tool's working directory
            parts = [shlex.join(p) for p in parts if p]
            while len(parts) > 1 and shortcut_commands(task, parts[-1:], app) == []: parts.pop()   # a check after the act ("move && get its size") can go
            sub = shortcut_commands(task, parts, app)
            if sub is None or '&&' in flow and sum(c.count(' + ') + 1 if PLACING.match(c) else 1 for c in sub) != len(parts): return None   # "check && act" without its check would act blind
            result += sub; continue
        original = tokens[:]
        helpers = (paths.ME, './rabik.py', 'rabik.py')
        if len(tokens) > 1 and (tokens[0] == sys.executable or os.path.basename(tokens[0]) in ('python', 'python3')) and tokens[1] in helpers:
            tokens = tokens[1:]
        if tokens[0] in helpers:
            tokens[0] = paths.ME
            if tokens != original: command = shlex.join(tokens)   # replay has neither the original cwd nor its Python launcher
        if policy.recursive_ask(tokens): return None
        if command.startswith((paths.REMEMBER, paths.ABOUT, paths.LOOK, paths.FRONT, paths.WINDOW, paths.SEARCH, paths.READ, paths.HISTORY, '<Read>', 'sleep ')): continue
        if tokens[:2] == [paths.ME, '--hands'] and tokens[2:3] == ['see']:
            if len(tokens) == 4: app = tokens[3]
            continue
        if tokens[0] == 'open' and len(tokens) in (3, 4) and tokens[1:-1] in (['-a'], ['-g', '-a']):
            app = tokens[-1]
            if not macos.wants_focus(task): command = f'{paths.SHOW} --bg {shlex.quote(app)}'
        elif os.path.basename(tokens[0]) == 'peekaboo':
            if tokens[1:3] != ['menu', 'click']: return None
            options, i = {}, 3
            while i < len(tokens):
                if tokens[i] == '--no-remote': i += 1; continue
                if tokens[i] not in ('--app', '--path') or i + 1 == len(tokens) or tokens[i] in options: return None
                options[tokens[i]] = tokens[i + 1]; i += 2
            if set(options) != {'--app', '--path'}: return None
            app = options['--app']; command = f'{paths.HANDS} menu {shlex.quote(app)} {shlex.quote(options["--path"])}'
        elif tokens[:3] == [paths.ME, '--hands', 'click'] and len(tokens) == 4 and '>' in tokens[3]:
            if not app: return None   # an old menu click with no app target must return to the AI, never use today's front app
            command = f'{paths.HANDS} menu {shlex.quote(app)} {shlex.quote(tokens[3])}'
        elif tokens[0] == 'osascript':
            lines = [re.sub(r'"(?:[^"\\]|\\.)*"', '""', s).strip() for i, t in enumerate(tokens) if i and tokens[i - 1] == '-e' for s in t.split('\n')]
            # a read: get/count/…, a value coerced "as string", a bare property "to name of current track", or a bare test 'application "X" is running'
            reads = [bool(re.search(r'\b(get|count|exists|return)\b|\bas (string|text|integer|number|real|boolean|list|record)\b|\bto \w+ of\b|^(?!.*\b(tell|if)\b).*\b(is|contains)\b', s, re.I)) and not re.search(r'\b(set|make|create|delete|click|press|perform|activate|open|close|quit|play|keystroke|key code|do shell script)\b', s, re.I) for s in lines]
            # every line reads or only frames one ("tell app" … "end tell"): "-e 'to pause' -e 'get its state'" still acts
            if any(reads) and all(r or re.fullmatch(r'tell (application|process) ""|end\b.*|delay [\d.]+|', s, re.I) for r, s in zip(reads, lines)): continue
        result.append(command)
    moving, merged = PLACING, []
    for command in result:   # back-to-back moves go at once (--place a + b), like the AI's own
        if merged and moving.match(command) and moving.match(merged[-1]): merged[-1] += ' +' + command[moving.match(command).end() - 1:]
        else: merged.append(command)
    return merged


def save_skills(sk):
    """Write learned tasks; one unused for 30 days goes (shortcuts the user made stay)."""
    old = time.strftime('%Y-%m-%d', time.localtime(time.time() - 30 * 86400))
    sk = {k: v for k, v in sk.items() if v.get('mine') or max(v.get('used', ''), v.get('at', '')) >= old}
    os.makedirs(paths.DIR, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=os.path.dirname(SKILLS), delete=False) as f:
        try:
            json.dump(sk, f, indent=1); f.flush(); os.replace(f.name, SKILLS)
        finally:
            if os.path.exists(f.name): os.unlink(f.name)


def learn(task, cmds, reply, asked=''):
    """Save the commands if every one is a replayable action (no reading, searching, clicking by element ID).
    asked: the words that asked for it when task is a shortcut's name, so "when I say study, open Notes" replays Notes in front."""
    k = wording.plain(task)
    if any(x in c for c in cmds for x in (paths.FORGET, paths.SHORTCUT)):   # changing rules or shortcuts is not itself a shortcut
        return
    # looking around (screen, menus, web, saving a rule) is how the AI found the way; the replay needs only the actions
    cmds = shortcut_commands(asked or task, cmds, (macos.cached_hands() or {}).get('app', ''))
    act = (paths.SHOW, paths.PLACE, paths.PLAY, paths.QUEUE, paths.TYPE, paths.HANDS, 'open ', 'osascript ')
    # 'make new': a reminder or note holds this moment's words ("make the task list" must not re-add old items)
    if not cmds or wording.DEICTIC.search(k) or wording.FAILED.search(reply) or not all(c.startswith(act) and hands.hands_replayable(c) and 'PID:' not in c and 'make new' not in c and not policy.risky(c) for c in cmds):
        return
    for command in cmds:
        try: bid = replay_quit(shlex.split(command))
        except ValueError: return
        if bid and apps.app_running(bid): return   # a quit that did not quit is evidence against the reply
    sk = skills()
    old = sk.get(k, {})
    new = old.get('cmds') != cmds
    said = asked or old.get('asked', '')   # a redo after a failed replay keeps what the user taught it as
    sk[k] = {'cmds': cmds, 'reply': reply, 'at': time.strftime('%Y-%m-%d'), **({'asked': said, 'mine': True} if said else {'mine': True} if old.get('mine') else {})}
    if asked:   # taught by name: no older version of it (a whole-sentence key, a rule, a workflow) may steer the AI or a replay
        name = r'\W+'.join(map(re.escape, k.split()))
        for other in [o for o in sk if o != k and re.search(rf'\bi say {name}\b', o)]: sk.pop(other)
        for rule in memory.memory_rules():
            if re.match(rf'\W*(?:when(?:ever)? i say\W+)?{name}\b', rule, re.I): memory.edit_rule(rule, '')
        workflows(k, None)
    save_skills(sk)
    return new   # True: a task it did not know yet (the box shows a green "Learned" tip)


def unlearn(task):
    sk = skills()
    if sk.pop(wording.plain(task), None) is not None:
        save_skills(sk)
    workflows(task, None)


def app_in(words):
    """The one app named in these words -> (the words with it as '{app}', the app), or None."""
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            app = apps.app_named(' '.join(words[i:i + n]))
            if app: return words[:i] + ['{app}'] + words[i + n:], app


def like(g, sk):
    """A learned task said another way -> (its key, (old app, new app) or None): the same words in any order,
    or the same words about another app ("put notes left" was learned, "put mail left" replays it for Mail).
    Words its commands use keep their order or come back to front ("on the left put notes"), so each app keeps its side:
    "notes left, mail right" never replays "mail left, notes right"."""
    def reordered(k, a, b):
        used = set(re.findall(r'[a-z0-9]+', ' '.join(sk[k]['cmds']).lower()))
        x, y = [w for w in a if w in used], [w for w in b if w in used]
        return sorted(a) == sorted(b) and y in (x, x[::-1])
    same = next((k for k in sk if reordered(k, wording.gist(k), g)), None)
    if same: return same, None
    new = app_in(g)
    if new:
        for k in sk:
            words = wording.gist(k)
            old = len(words) == len(g) and app_in(words)
            if old and old[1] != new[1] and reordered(k, old[0], new[0]) and swapped(sk[k]['cmds'], old[1], new[1]):
                return k, (old[1], new[1])
    return None, None


def swapped(cmds, old, new):
    """The commands with app old -> new, or None when old also hides inside a script ("tell process \"Notes\"")."""
    out = []
    for c in cmds:
        try: tokens = [new if t == old else t for t in shlex.split(c)]
        except ValueError: return None
        if any(old in t for t in tokens): return None
        out.append(shlex.join(tokens))
    return out if any(new in c for c in out) else None


def replay_quit(tokens):
    """A learned plain AppleScript quit -> bundle id, so display and process names cannot lie."""
    if len(tokens) != 3 or tokens[:2] != ['osascript', '-e']:
        return None
    m = re.fullmatch(r'tell application( id)? "([^"]+)" to quit', tokens[2], re.I)
    if not m:
        return None
    return m[2] if m[1] else apps.app_id(apps.app_named(m[2]) or m[2])


@dataclass
class ReplayResult:
    """One replay of a learned shortcut: its reply (None: the AI takes over), the commands it chose, what each step said
    (ran, for the ask log and a redo), and the step that failed."""
    reply: object = None
    commands: list = field(default_factory=list)
    ran: list = field(default_factory=list)
    failed_at: object = None


def replay(k, swap=None):
    result = ReplayResult()
    result.reply = _replay(k, swap, result)
    return result


def _replay(k, swap, result):
    s = skills().get(k)
    asked = s.get('asked') or k if s else k   # a named shortcut's own words say nothing about focus; the words that taught it do
    commands = shortcut_commands(asked, swapped(s['cmds'], *swap) if swap else s['cmds']) if s else None
    if not commands:
        return None
    result.commands = commands
    if prefs.pref('safe', True) and any(policy.risky(c) for c in commands):
        return None   # the AI's tool gate can show the Allow card; direct replay cannot
    if not macos.wants_focus(asked) and prefs.pref('workIn', 'back') != 'front' and any(policy.focus_command(c) for c in commands): return None
    for index, c in enumerate(commands):   # any failure: hand it to the AI instead
        result.failed_at = index
        try:
            tokens = shlex.split(c)
            with environ.requested(asked):   # each step trusts the words that taught it, then the ask's own again
                if tokens[:2] == [paths.ME, '--show'] and (len(tokens) == 3 or len(tokens) == 4 and tokens[2] == '--bg'):
                    reply = web.show(tokens[-1], '--bg' in tokens)   # as the verified run did: the model chose front or --bg from the words in any language
                    result.ran.append(f'{c[:200]}  => {reply[:200]}')
                    if reply.startswith(('could not', 'no app or file')): return None
                elif tokens[:2] == [paths.ME, '--hands']:
                    out, ok = hands.hands(*tokens[2:])
                    result.ran.append(f'{c[:200]}  => {out[:200]}')
                    if not ok: return None
                elif tokens[:2] == [paths.ME, '--place']:
                    began = time.time()
                    out = windows.place_many(tokens[2:])
                    result.ran.append(f'{c[:200]}  => {out[:200]} ({time.time() - began:.1f}s)')
                    if windows.place_failed(out): return None
                elif (bid := replay_quit(tokens)) is not None:
                    if not bid: return None
                    began = time.time()
                    closed = apps.quit_app(bid)
                    result.ran.append(f'{c[:200]}  => {"closed" if closed else "still open"} ({time.time() - began:.1f}s)')
                    if not closed: return None
                else:
                    if policy.ARRANGE.search(c): macos.free_focus()
                    began = time.time()
                    r = subprocess.run(['/bin/zsh', '-c', c], capture_output=True, text=True, timeout=20, env={**os.environ, 'RABIK_REQUEST': asked})
                    result.ran.append(f'{c[:200]}  => {(r.stdout.strip() or r.stderr.strip() or "exit " + str(r.returncode))[:200]} ({time.time() - began:.1f}s)')   # what each step said, and how long
                    if r.returncode or wording.FAILED.search(r.stdout) or 'no window found' in r.stdout: return None   # a step that says it failed is a failure: the AI takes over
                    if tokens[0] == 'open' and len(tokens) in (3, 4) and tokens[1:-1] in (['-a'], ['-g', '-a']) and (bid := apps.app_id(apps.app_named(tokens[-1]) or tokens[-1])) and not apps.app_up(bid):
                        result.ran.append(f'{tokens[-1]} => not running'); return None   # exit 0 is not proof: check by bundle id, as quit does
                    macos.preview_commands(c)
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            result.ran.append(f'{c[:200]}  => {type(e).__name__}')
            return None
    if s.get('used') != time.strftime('%Y-%m-%d'):   # used today: the 30-day clock starts again
        sk = skills(); sk[k]['used'] = time.strftime('%Y-%m-%d'); save_skills(sk)
    result.failed_at = None
    return outcome(s['reply'].replace(*swap) if swap else s['reply'])


def outcome(reply):
    """A learned reply's first sentence: the rest told how that first run went (its checks, guesses), which a replay did not do."""
    m = re.match(r'[^"“”]+?[a-z0-9)]{2}[.!?](?=\s+[A-Z])', reply)   # never inside a quote or after an abbreviation ("Hail Pl.", "e.g.")
    return m[0] if m and not re.search(r"n['’]t\b|\bnot\b", reply[m.end():], re.I) else reply   # a caveat ("It isn't sent yet.") holds for every replay


def workflows(task=None, method=''):
    """One relevant procedure in the prompt; never execute historical UI commands blindly."""
    path = os.path.join(paths.DIR, 'workflows.json')
    try:
        with open(path) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    saved = {k: v for k, v in saved.items() if isinstance(v, str)} if isinstance(saved, dict) else {}
    if task is None:
        return saved
    changed = False
    if method:
        saved.pop(wording.plain(task), None)
        saved[wording.plain(task)] = method[:800]
        changed = True
    words = lambda text: set(re.findall(r'[a-z0-9]+', re.sub(r'\b(make|create|start)\b', 'start', wording.plain(text)))) - wording.STOP
    want = words(task)
    hits = [(1 if k == wording.plain(task) else len(want & words(k)) / max(1, len(words(k))), k, v) for k, v in saved.items()
            if k == wording.plain(task) or len(want & words(k)) >= 2]
    score, key, value = max(hits, default=(0, '', ''))
    if method is None:
        if score >= .6:
            saved.pop(key)
            changed = True
    if changed:
        os.makedirs(paths.DIR, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=paths.DIR, delete=False) as f:
            json.dump(saved, f, indent=1)
        os.replace(f.name, path)   # cancellation cannot truncate previously learned procedures
    if method is None or method:
        return method[:800] if method else ''
    return f'Previous task: {key[:200]}\nProcedure: {value}' if score >= .6 else ''


def replayable(cmd):
    """An AI-written replay runs later with no AI: only plain actions, nothing that reads the screen, clicks a spot or deletes."""
    return not (UNSAFE.search(re.sub(r'"[^"$`]*"', '""', cmd)) or policy.risky(cmd) or re.search(r'--(coords|at|on)\b|PID:|make new|<\w+>', cmd) or not hands.hands_replayable(cmd))


def remember_workflow(task, reply, ok, cmds):
    again = re.search(r'\s*\[replay (.+)\]\s*$', reply)
    reply = reply[:again.start()] if again else reply
    match = re.search(r'\[workflow (.+)\]\s*$', reply, re.S)
    if not match:
        return reply, False
    reply = (reply[:match.start()] + reply[match.end():]).strip()
    saved = bool(prefs.pref('learn', True) and ok and cmds and reply and not
                 wording.FAILED.search(reply))
    title, sep, method = match[1].partition('|')
    saved = saved and bool(sep and title.strip() and method.strip())
    if saved:
        workflows(title.strip()[:120], method.strip())
        if again and replayable(again[1]):
            commands = shortcut_commands(task, [again[1].strip()], (macos.cached_hands() or {}).get('app', ''))
            performed = shortcut_commands(task, cmds, (macos.cached_hands() or {}).get('app', ''))
            if not commands or performed is None or any(c not in performed for c in commands): return reply, saved
            sk = skills()
            for k in {wording.plain(task), wording.plain(title)}:
                sk[k] = {'cmds': commands, 'reply': reply, 'at': time.strftime('%Y-%m-%d')}
            save_skills(sk)
    return reply, saved
