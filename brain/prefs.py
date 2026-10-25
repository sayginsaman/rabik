"""Settings (settings.json, shared with Rabik.app) and the AI client and model they choose."""
import json
import os
import subprocess
import urllib.error
import urllib.parse
from brain import environ, paths, storage

__all__ = ['pref', 'save_pref', 'routing_mode', 'work_model', 'main_model', 'server', '_models_at', 'models', 'LOCAL_SERVERS',
           'local_servers', 'client', 'agent_model', 'routine_model']


def pref(key, default):
    try:
        with open(paths.PREFS) as f:
            return json.load(f).get(key, default)
    except (OSError, ValueError):
        return default   # recent: Rabik.app deletes it on ✕


def save_pref(key, value):
    try:
        with open(paths.PREFS) as f: values = json.load(f)
    except (OSError, ValueError):
        values = {}
    os.makedirs(os.path.dirname(paths.PREFS), mode=0o700, exist_ok=True)
    storage.private_json(paths.PREFS, {**(values if isinstance(values, dict) else {}), key: value})


def routing_mode():
    mode = pref('routing', '')
    if mode in ('cheapest', 'balanced', 'capable'): return mode
    if pref('model', 'haiku') != 'haiku': return 'capable'
    return 'balanced' if pref('escalate', True) and pref('escalateAuto', True) else 'cheapest'


def work_model():
    model = pref('model', 'haiku')
    if model == 'haiku': model = pref('agentModel', 'sonnet')
    return model if model != 'haiku' else 'sonnet'


def main_model():
    if server(): return pref('model', 'haiku')
    return work_model() if routing_mode() == 'capable' else 'haiku'


def server(model=None):
    """Settings → Custom server: env that points `claude` at another server with Claude's API (DeepSeek, Ollama, LM Studio, vLLM)."""
    base, model = str(pref('apiBase', '')).strip(), str(pref('apiModel', '') if model is None else model).strip()
    if not base: return {}
    env = {'ANTHROPIC_BASE_URL': base, 'ANTHROPIC_AUTH_TOKEN': str(pref('apiKey', '')).strip() or 'none', 'ANTHROPIC_API_KEY': ''}   # local servers take any key
    return {**env, **{f'ANTHROPIC_DEFAULT_{m}_MODEL': model for m in ('HAIKU', 'SONNET', 'OPUS') if model}}   # Rabik asks for haiku/sonnet; both become this model


def _models_at(url, key='', timeout=4):
    import urllib.request   # here, not at the top: with http.client and ssl it costs every helper start ~9 ms (the tool gate runs before each tool call)
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {key}', 'x-api-key': key, 'anthropic-version': '2023-06-01'})
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        error.close()
        raise
    with response:
        return [m['id'] for m in json.load(response).get('data', []) if isinstance(m, dict) and m.get('id')]


def models():
    """The custom server's model names, for Settings' Model box. /v1/models is the same list shape on OpenAI-style and Anthropic-style servers."""
    probe = environ.probe_base()   # setup's Change provider asks about a server before it is saved
    base = str(pref('apiBase', '') if probe is None else probe).strip().rstrip('/')
    key = str(pref('apiKey', '') if probe is None else environ.probe_key('')).strip()
    try: u = urllib.parse.urlparse(base)
    except ValueError: return []
    if u.scheme not in ('http', 'https') or not u.hostname: return []
    root = f'{u.scheme}://{u.netloc}'   # DeepSeek's Claude address ends in /anthropic; its list lives at the root
    for url in dict.fromkeys([base + '/v1/models', root + '/v1/models', root + '/models']) if u.netloc else []:
        try:
            ids = _models_at(url, key)
            if ids: return ids
        except (OSError, ValueError, AttributeError, TypeError):   # a server's odd list ({"data": null}) is just no list
            continue
    return []


LOCAL_SERVERS = (
    ('Ollama', 'http://localhost:11434', 'http://127.0.0.1:11434'),
    ('LM Studio', 'http://localhost:1234', 'http://127.0.0.1:1234'),
    ('llama.cpp', 'http://localhost:8080', 'http://127.0.0.1:8080'),
    ('vLLM', 'http://localhost:8000', 'http://127.0.0.1:8000'),
)


def local_servers():
    """Local Claude-style servers already listening on their standard ports, discovered only through GET /v1/models."""
    def probe(row):
        name, base, address = row
        try:
            # macOS curl bounds the whole transfer and never uses proxies, redirects or user curl settings.
            response = subprocess.run(['/usr/bin/curl', '-q', '--silent', '--fail', '--noproxy', '*',
                                       '--max-time', '0.5', '--max-filesize', '1048576', address + '/v1/models'],
                                      capture_output=True, timeout=1)
            if response.returncode: return None
            found = [m['id'] for m in json.loads(response.stdout).get('data', []) if isinstance(m, dict) and isinstance(m.get('id'), str) and m['id']]
            return {'name': name, 'base': base, 'models': found} if found else None
        except (OSError, ValueError, AttributeError, TypeError, subprocess.TimeoutExpired):
            return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(LOCAL_SERVERS)) as pool:
        return [found for found in pool.map(probe, LOCAL_SERVERS) if found]


def client():
    """The configured AI client name; anything unrecognized falls back to 'claude'."""
    c = pref('client', 'claude')
    return c if c in ('claude', 'devin', 'pi') else 'claude'


def agent_model():
    if str(pref('apiBase', '')).strip():
        return str(pref('agentApiModel', '')).strip() or str(pref('apiModel', '')).strip() or pref('model', 'haiku')
    return 'haiku' if routing_mode() == 'cheapest' else work_model()


def routine_model(mode):
    if str(pref('apiBase', '')).strip(): return agent_model()
    return 'haiku' if mode == 'cheapest' else work_model()
