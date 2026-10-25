"""The AI client processes an ask starts (Claude Code, Devin, Pi): can Rabik think (plan), starting Claude Code with
its tools and the gate, Devin and Pi settings, and stopping a client with everything it started."""
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse
from brain import environ, paths, policy, prefs, prompts, storage, turn

__all__ = ['stop_claude', 'plan', 'claude_plan', 'devin_plan', 'pi_plan', 'devin_config', 'delete_devin_session', 'stop_devin',
           'PI_GATE', 'stop_workers', 'user_agent_tools', 'copy_agent_skills', 'start_ai', 'start_claude']


def stop_claude(p):
    try:
        os.killpg(p.pid, signal.SIGTERM)   # hands releases a held mouse button before the hard stop
        time.sleep(.05)
        os.killpg(p.pid, signal.SIGKILL)   # includes running tools and permission hooks
    except OSError:   # already gone, or its group is out of reach (EPERM): nothing left to stop
        pass


def plan():
    """Can Rabik think? The configured AI client must be installed and signed in.
    -> {'ok': bool, 'need': '' | 'install' | 'login' | 'upgrade', 'client': name, 'text': one line for the user}"""
    if prefs.client() == 'devin': return {**devin_plan(), 'client': 'devin'}
    if prefs.client() == 'pi': return {**pi_plan(), 'client': 'pi'}
    return {**claude_plan(), 'client': 'server' if prefs.server() else 'claude'}


def claude_plan():
    """Claude Code must be installed and signed in to a paid Claude plan (or an API key)."""
    custom = prefs.server()
    if custom:
        try:
            address = urllib.parse.urlparse(custom['ANTHROPIC_BASE_URL'])
            host = address.hostname if address.scheme in ('http', 'https') else ''
        except ValueError:
            host = ''
        if not host:
            return {'ok': False, 'need': '', 'text': 'Enter a valid custom server address in Settings.'}
    if custom and shutil.which('claude'):   # no Claude sign-in needed
        return {'ok': True, 'need': '', 'text': f'Using your custom server, {host}.'}
    if custom:
        return {'ok': False, 'need': 'install', 'text': 'Custom servers run through Claude Code. Install it; no Claude account needed.'}
    try:
        s = json.loads(subprocess.run(['claude', 'auth', 'status'], capture_output=True, text=True, timeout=20).stdout)
    except FileNotFoundError:
        return {'ok': False, 'need': 'install', 'text': 'Claude Code is not installed.'}
    except (ValueError, subprocess.TimeoutExpired):
        return {'ok': False, 'need': 'login', 'text': 'Could not read your Claude sign-in.'}
    if not s.get('loggedIn'):
        return {'ok': False, 'need': 'login', 'text': 'Sign in to Claude to start.'}
    if s.get('authMethod') != 'claude.ai':
        return {'ok': True, 'need': '', 'text': 'Using your Anthropic API key (billed per use).'}
    sub = (s.get('subscriptionType') or '').lower()
    if sub in ('', 'free'):
        return {'ok': False, 'need': 'upgrade', 'text': 'Rabik needs a paid Claude plan (Pro or Max).'}
    return {'ok': True, 'need': '', 'text': f'Using your Claude {sub.title()} plan.'}


def devin_plan():
    """Devin must be installed and signed in (`devin auth login`)."""
    if not shutil.which('devin'):
        return {'ok': False, 'need': 'install', 'text': 'Devin is not installed.'}
    try:
        s = subprocess.run(['devin', 'auth', 'status'], capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'need': 'login', 'text': 'Could not read your Devin sign-in.'}
    if s.returncode:
        return {'ok': False, 'need': 'login', 'text': 'Sign in to Devin to start.'}
    return {'ok': True, 'need': '', 'text': 'Using your Devin plan.'}


def pi_plan():
    """Pi owns its provider, model and sign-in; Rabik only needs its CLI."""
    if not shutil.which('pi'):
        return {'ok': False, 'need': 'install', 'text': 'Pi is not installed.'}
    return {'ok': True, 'need': '', 'text': 'Using the provider and model selected in Pi.'}


def devin_config(directory):
    """An isolated Devin project with only the Claude-equivalent tools, every call gated."""
    folder = os.path.join(directory, '.devin')
    os.makedirs(folder)
    available = ['read', 'grep', 'glob', 'exec', 'Fetch(*)']
    deny = ['edit', 'Write(**)', 'mcp__*']
    config = {
        'read_config_from': {name: False for name in ('agents_standard', 'cursor', 'windsurf', 'claude', 'copilot', 'opencode', 'zed')},
        'permissions': {'allow': available, 'deny': deny + [f'Exec({cmd})' for cmd in policy.DENIED]},
    }
    config['hooks'] = {'PreToolUse': [{'matcher': '.*', 'hooks': [{
        'type': 'command', 'command': f'RABIK_CLIENT=devin /bin/sh "{paths.ME}" --gate || exit 2', 'timeout': 140}]}]}
    path = os.path.join(folder, 'config.json')
    with open(path, 'w') as f:
        json.dump(config, f)
    return path


def delete_devin_session(directory):
    """Delete the one CLI session created in this per-ask working directory."""
    try:
        result = subprocess.run(['devin', 'list', '--format', 'json'], cwd=directory, capture_output=True, text=True, timeout=10)
        if result.returncode:
            return False
        rows = json.loads(result.stdout)
        rows = rows.get('sessions', []) if isinstance(rows, dict) else rows
        row = next((r for r in rows if os.path.realpath(r.get('cwd') or '') == os.path.realpath(directory)), None)
        session = (row or {}).get('id') or (row or {}).get('session_id')
        return bool(session) and not subprocess.run(
            ['devin', 'rm', session, '--force'], cwd=directory, capture_output=True, timeout=10).returncode
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        return False


def stop_devin(p, directory):
    stop_claude(p)
    delete_devin_session(directory)


PI_GATE = r'''
import { spawnSync } from "node:child_process";
export default function (pi) {
  const names = { bash: "exec", read: "read", grep: "grep", find: "glob", ls: "read" };
  pi.on("tool_call", (event, ctx) => {
    const payload = JSON.stringify({ tool_name: names[event.toolName] || event.toolName, tool_input: event.input, cwd: ctx.cwd });
    const result = spawnSync("/bin/sh", [process.env.RABIK_ME, "--gate"], {
      input: payload, encoding: "utf8", env: { ...process.env, RABIK_CLIENT: "pi" }
    });
    try {
      const answer = JSON.parse((result.stdout || "").trim().split("\n").at(-1));
      if (result.status === 0 && answer.decision === "approve") return;
      return { block: true, reason: answer.reason || "Rabik blocked this tool call." };
    } catch {
      return { block: true, reason: "Rabik could not verify this tool call." };
    }
  });
}
'''


def stop_workers(*_):
    turn.STOPPING = True
    turn.end_turn()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if os.getpgrp() == os.getpid():
        os.killpg(os.getpid(), signal.SIGTERM)
    sys.exit(0)


def user_agent_tools(directory):
    """Explicit tool-only plugins avoid loading personal settings hooks or CLAUDE.md."""
    flags, servers = [], {}
    for path in (os.path.join(paths.HOME, '.claude.json'), os.path.join(paths.HOME, '.claude', 'settings.json')):
        try:
            with open(path) as f: servers.update(json.load(f).get('mcpServers', {}))
        except (OSError, ValueError, TypeError): pass
    plugin_root = os.path.join(directory, 'tool-plugins')
    os.makedirs(plugin_root, mode=0o700, exist_ok=True)
    sources = [('user-tools', os.path.join(paths.HOME, '.claude'))]
    try:
        with open(os.path.join(paths.HOME, '.claude', 'settings.json')) as f: enabled = json.load(f).get('enabledPlugins', {})
        with open(os.path.join(paths.HOME, '.claude', 'plugins', 'installed_plugins.json')) as f: installed = json.load(f).get('plugins', {})
        for name, versions in installed.items():
            if enabled.get(name) is True:
                source = next((v.get('installPath') for v in versions if v.get('scope') == 'user'), None)
                if source: sources.append((name.split('@')[0], source))
    except (OSError, ValueError, TypeError, AttributeError): pass
    for index, (name, source) in enumerate(sources):
        target = os.path.join(plugin_root, str(index)); os.makedirs(os.path.join(target, '.claude-plugin'), mode=0o700, exist_ok=True)
        storage.private_json(os.path.join(target, '.claude-plugin', 'plugin.json'), {'name': name})
        for part in ('skills', 'commands'):
            path, destination = os.path.join(source, part), os.path.join(target, part)
            if os.path.isdir(path): copy_agent_skills(path, destination)
        if index:
            for part in os.listdir(source):
                path, link = os.path.join(source, part), os.path.join(target, part)
                if part not in ('skills', 'commands', 'hooks', 'CLAUDE.md', '.claude-plugin', '.mcp.json') and not os.path.lexists(link): os.symlink(path, link)
        try:
            with open(os.path.join(source, '.mcp.json')) as f: config = json.load(f)
            raw = json.dumps(config.get('mcpServers', config)).replace('${CLAUDE_PLUGIN_ROOT}', source)
            servers.update({'plugin_' + re.sub(r'[^\w-]', '_', name) + '_' + key: value for key, value in json.loads(raw).items()})
        except (OSError, ValueError, TypeError): pass
    flags += ['--plugin-dir', plugin_root]
    storage.private_json(os.path.join(paths.agent_gate_dir(directory), 'user-mcp.json'), servers)
    return flags


def copy_agent_skills(source, destination, visited=None):
    visited = set() if visited is None else visited
    real = os.path.realpath(source)
    if real in visited: return
    visited = visited | {real}
    os.makedirs(destination, mode=0o700, exist_ok=True)
    for name in os.listdir(source):
        path, target = os.path.join(source, name), os.path.join(destination, name)
        if os.path.isdir(path): copy_agent_skills(path, target, visited)
        elif name.lower().endswith('.md'):
            try:
                with open(path) as f: text = f.read()
            except (OSError, UnicodeError): continue
            # Rebuild metadata rather than parsing YAML: skill/command hooks, aliases and merges cannot survive.
            text = text.replace('\r\n', '\n').lstrip('\ufeff')
            if text.startswith('---\n'):
                head, sep, body = text[4:].partition('\n---')
                if sep:
                    description = re.search(r'^description:\s*(.*(?:\n[ \t]+.*)*)', head, re.M)
                    label = ' '.join(description[1].strip().strip('>|').split())[:600] if description else name.removesuffix('.md')
                    text = '---\nname: ' + json.dumps(os.path.basename(source) if name == 'SKILL.md' else name.removesuffix('.md')) + '\ndescription: ' + json.dumps(label) + '\n---' + body
            with open(target, 'w') as f: f.write(text)
            os.chmod(target, 0o600)
        elif not os.path.lexists(target): os.symlink(path, target)


def start_ai(model=None):
    """Warm the configured client ahead of the request. Claude waits on stdin; Devin and Pi start after confirmation."""
    return start_claude(model) if prefs.client() == 'claude' else None


def start_claude(model=None, agent=None):
    """`claude -p` started ahead, waiting for the request on stdin: its ~1 s startup happens while the user is still talking."""
    claude = environ.claude() or shutil.which('claude')
    if not claude:
        return None
    system = prompts.system_prompt(prompts.ASK_FIRST if prefs.pref('safe', True) else prompts.NEVER)
    if agent:
        for main_only in (prompts.AGENT_HANDOFF, prompts.DRAWING, prompts.POINTER, prompts.TEACH, prompts.WORKFLOW): system = system.replace(main_only, '')   # [tip]/[workflow]/[point] are read only from main replies
        system += prompts.AGENT_SYSTEM + ('\nPersonal tools are enabled.' if prefs.pref('agentUserTools', True) else '\nPersonal tools are disabled; do not request them.')
    settings = {}
    ask = agent['directory'] if agent else environ.ask_dir() or tempfile.mkdtemp(prefix='rabik-ask-')   # keep helpers and focus restoration on the same ask
    if not agent: atexit.register(shutil.rmtree, ask, True)
    if prefs.pref('safe', True):   # main asks and agents alike; what SAFE_OUT lists and what a card allows run outside
        system += prompts.SANDBOX
        settings['sandbox'] = {'enabled': True, 'autoAllowBashIfSandboxed': True, 'allowUnsandboxedCommands': True, 'excludedCommands': policy.SAFE_OUT}
        settings['sandbox']['filesystem'] = {'denyRead': [os.path.join(paths.DIR, 'agent-gates')], 'denyWrite': [os.path.join(paths.DIR, 'agent-gates'), os.path.join(paths.DIR, 'answers')]}
    if agent and agent.get('connectors'):
        try:
            with open(os.path.join(paths.DIR, 'agent-connectors.json')) as f: connectors = json.load(f)
            settings['deniedMcpServers'] = [{'serverName': c['name']} for c in connectors if not any(n.startswith(c['prefix']) or n == c['prefix'].rstrip('_') for n in agent['connectors'])]
        except (OSError, ValueError, KeyError): pass
    settings['hooks'] = {'PreToolUse': [{'matcher': '.*', 'hooks': [{'type': 'command', 'command': f'/bin/sh "{paths.ME}" --gate', 'timeout': 660 if agent else 140}]}]}
    errors = tempfile.TemporaryFile(mode='w+')   # draining a pipe only after wait() can deadlock
    flags = ['--resume', agent['session']] if agent and agent.get('session') else []
    flags += ['--include-partial-messages'] + ([] if agent else ['--no-session-persistence', '--strict-mcp-config'])
    if agent and prefs.pref('agentUserTools', True): flags += user_agent_tools(ask)
    if not agent: flags += ['--disable-slash-commands']
    elif not prefs.pref('agentUserTools', True): flags += ['--disable-slash-commands']
    env = {**os.environ, 'RABIK_ASK': ask}
    # Messages take the cheaper 5-minute cache (steps are seconds apart; a later follow-up rewrites once); tools + system keep Claude's default.
    env['CLAUDE_CODE_MESSAGES_PROMPT_CACHE_TTL'] = '5m'
    if agent:
        for key in ('RABIK_COMMIT', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'RABIK_REQUEST'): env.pop(key, None)
        env.update(RABIK_AGENT=agent['id'], RABIK_HANDS_STATE=os.path.join(ask, 'hands.json'), RABIK_FRONT=agent.get('app', ''), RABIK_UI='1',
                   RABIK_AGENT_PREP='1' if agent.get('destination') == 'meeting' else '0', CLAUDE_CODE_DISABLE_CLAUDE_MDS='1')
    env.update(prefs.server(prefs.agent_model() if agent else None))
    tools = 'Bash,Read,WebSearch,WebFetch'
    if agent:
        tools = 'Read,WebSearch,WebFetch,ToolSearch' if agent.get('destination') == 'meeting' else 'Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Skill,ToolSearch'
        if agent.get('connectors'): tools += ',' + ','.join(agent['connectors'])
    try:
        p = subprocess.Popen([claude, '-p', '--input-format', 'stream-json', '--model', model or prefs.main_model(), '--effort', 'low', '--system-prompt', system,
                              '--tools', tools, '--permission-mode', 'dontAsk' if agent else 'bypassPermissions', '--disallowedTools', *policy.DENY,
                              '--settings', json.dumps(settings), '--setting-sources', '', '--output-format', 'stream-json', '--verbose', *flags],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True, cwd=ask if agent else tempfile.gettempdir(), start_new_session=True, env=env)
    except BaseException:
        errors.close()
        raise
    p.ask, p.errors, p.rabik_model = ask, errors, model or prefs.main_model()
    if not agent:
        atexit.register(errors.close); atexit.register(stop_claude, p)
    if not agent: signal.signal(signal.SIGTERM, lambda *_: (stop_claude(p), stop_workers()))
    return p
