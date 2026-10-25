"""The web: fetch and search, opening URLs, files and apps where the user sees them (show), background tabs, and driving
the browser (web()). show and web() call each other, so they live together."""
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
from brain import apps, environ, hands, interaction, macos, paths, policy, prefs, protocol, storage, windows

__all__ = ['get', 'text_of', 'search', 'WEB_JS', 'RISKY_CLICK', 'browser_terms', 'browser_adapter', 'close_agent_window',
           'work_page', 'running_app', 'page_ready', 'web', 'connectors', 'show', 'background_tab', 'remember_background_tab']


def background_tab(url, app):
    """Navigate Rabik's last background page in place; making a new browser tab can activate its app."""
    saved_path = os.path.join(environ.ask_dir(paths.DIR) if environ.agent() else paths.DIR, 'background-page.json')
    try:
        with open(saved_path) as f: saved = json.load(f)
        adapter = browser_adapter(app)
        if saved.get('app') != app or saved.get('adapter') != adapter or adapter not in ('chromium', 'webkit'):
            return False
        window, tab = saved['window'], saved['tab']
        if not all(isinstance(i, int) and i > 0 for i in (window, tab)) or not isinstance(saved.get('url'), str):
            return False
        quoted = app.replace('\\', '\\\\').replace('"', '\\"')
        target = f'first tab of window id {window} whose id is {tab}' if adapter == 'chromium' else f'tab {tab} of window id {window}'
        script = (f'on run argv\ntell application "{quoted}"\nset t to {target}\n'
                  'if (URL of t as text) is not item 1 of argv then error "Rabik page changed"\n'
                  'set URL of t to item 2 of argv\nend tell\nend run')
        r = subprocess.run(['osascript', '-e', script, saved['url'], url], capture_output=True, text=True, timeout=1)
        if r.returncode: return False
        page = {'app': app, 'adapter': adapter, 'window': window, 'tab': tab, 'target': None}
        path = os.path.join(environ.ask_dir(paths.DIR), 'web.json')
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        storage.private_json(path, page)
        return True
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return False


def remember_background_tab(app):
    """Remember only a tab Rabik just opened or reused, including its final URL after redirects."""
    page_path = os.path.join(environ.ask_dir(paths.DIR), 'web.json')
    try:
        with open(page_path) as f: page = json.load(f)
        adapter, window, tab = page['adapter'], page['window'], page['tab']
        quoted = app.replace('\\', '\\\\').replace('"', '\\"')
        target = f'first tab of window id {window} whose id is {tab}' if adapter == 'chromium' else f'tab {tab} of window id {window}'
        r = subprocess.run(['osascript', '-e', f'tell application "{quoted}" to get URL of {target}'],
                           capture_output=True, text=True, timeout=1)
        url = (r.stdout or '').strip()
        if r.returncode or not url: return
        saved = {'app': app, 'adapter': adapter, 'window': window, 'tab': tab, 'url': url}
        os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
        path = os.path.join(environ.ask_dir(paths.DIR) if environ.agent() else paths.DIR, 'background-page.json')
        with open(path + '.tmp', 'w') as f: json.dump(saved, f)
        os.chmod(path + '.tmp', 0o600); os.replace(path + '.tmp', path)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        pass


def show(target, bg=False):
    """Open a URL, file or app where the user can see it, then hand focus back to the app the user was using.
    bg: a page Rabik works in by itself opens behind, so the user keeps working (the mini screen shows it)."""
    t = os.path.expanduser(target)
    if re.match(r'^https?://', t) and not policy.agent_url_allowed(t): return policy.agent_url_denial()
    if environ.agent() and re.match(r'^https?://', t) and not (macos.wants_focus() or prefs.pref('workIn', 'back') == 'front' and macos.wants_focus(None, True)):
        return web('read', t)
    mine = '' if bg and environ.focus_guard() else macos.osa('tell application "System Events" to get name of first process whose frontmost is true') if bg else macos.front()[0]
    ahead = bg and prefs.pref('workIn', 'back') == 'front'
    if bg:
        is_url = bool(re.match(r'^[a-z]+:', t))
        browser = ''
        if not ahead and re.match(r'^https?://', t):
            browser = running_app(t)
            if browser and background_tab(t, browser):
                status = web('wait', text=t, app=browser)
                remember_background_tab(browser)
                return f'opened {target} in the background' + (f'\n{status}' if status != 'Page ready.' else '')
        if subprocess.run(['open'] + ([] if ahead else ['-g']) + ([t] if is_url or os.path.exists(t) else ['-a', t])).returncode:
            return f'could not open {target}'
        target_window = macos.preview_app(t, 'open')
        launched = target_window.get('app') if isinstance(target_window, dict) else t if not is_url and not os.path.exists(t) else ''
        if not ahead: windows.keep_behind(mine, launched)
        if re.match(r'^https?://', t):
            browser = (target_window.get('app', '') if isinstance(target_window, dict) else browser) or running_app(t)
            status = web('wait',text=t,app=browser,fresh=True) if browser else 'Page readiness unavailable. Read the page before acting.'
            if browser: remember_background_tab(browser)
            where = 'in front' if ahead else 'in the background'
            if status != 'Page ready.': return f'opened {target} {where}\n{status}'
            return f'opened {target} {where}'
        return f'opened {target} ' + ('in front' if ahead else 'in the background')
    if prefs.pref('openOn', 'here') == 'here':   # This screen = in front, like a double-click
        macos.free_focus(user=True)
        r = subprocess.run(['open', t] if re.match(r'^[a-z]+://', t) or os.path.exists(t) else ['open', '-a', t])
        return f'no app or file called "{target}"' if r.returncode else f'opened {target} in front'
    if re.match(r'^[a-z]+://', t) or os.path.exists(t):
        subprocess.run(['open', '-g', t])
        js = ('ObjC.import("AppKit"); var t = %s; var u = /^[a-z]+:\\/\\//.test(t) ? $.NSURL.URLWithString(t) : $.NSURL.fileURLWithPath(t); '
              '$.NSWorkspace.sharedWorkspace.URLForApplicationToOpenURL(u).path.js') % json.dumps(t)
        app = os.path.basename(subprocess.run(['osascript', '-l', 'JavaScript', '-e', js], capture_output=True, text=True).stdout.strip())[:-4]
    else:
        if subprocess.run(['open', '-g', '-a', t]).returncode:
            return f'no app or file called "{target}"'
        app = t
    scr, other = macos.screens(), None
    if len(scr) > 1 and app and app != mine:
        for _ in range(15):   # wait for its window, at most 1.5 s
            if macos.osa(f'tell application "System Events" to count windows of process "{macos.osa_quote(apps.proc_of(app))}"') not in ('', '0'):
                break
            time.sleep(0.1)
        try:
            x = int(macos.osa(f'tell application "System Events" to tell process "{mine}" to get position of window 1').split(', ')[0])
        except ValueError:
            x = 0
        other = next((s[0] for s in scr if not s[1] <= x + 50 < s[1] + s[3]), None)
        if other:
            windows.place(app, 'center', other)
        if not macos.wants_focus() and prefs.pref('workIn', 'back') != 'front':
            macos.osa(f'tell application "System Events" to set frontmost of process "{mine}" to true')
    return f'opened {target} in {app or "its app"}' + (f' on {other}' if other else '')


def get(url, timeout=10):
    import urllib.request   # here, not at the top: with http.client and ssl it costs every helper start ~9 ms (the tool gate runs before each tool call)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/605 Safari/605'})
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        error.close()
        raise
    with response:
        body, final = response.read().decode('utf-8', 'replace'), response.geturl()
    if policy.managed_agent():
        links = [urllib.parse.urljoin(final, html.unescape(link)) for link in re.findall(r'''(?i)\bhref\s*=\s*["']([^"'#]+)''', body[:1000000])]
        policy.agent_url_observe(environ.ask_dir(required=True), [final, *links])
    return body


def text_of(h):
    h = re.sub(r'(?is)<(script|style|noscript|svg|head|nav|header|footer|aside)\b.*?</\1>', ' ', h)
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', h)).split())


def search(q):
    """Free web search: DuckDuckGo's HTML page -> 5 results, ~150 tokens each."""
    page = get('https://html.duckduckgo.com/html/?q=' + urllib.parse.quote(q))
    out = []
    for u, t, sn in re.findall(r'class="result__a" href="([^"]+)">(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', page, re.S)[:5]:
        u = urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(u)).query).get('uddg', [u])[0]
        out.append([text_of(t), u, text_of(sn)])
    def page(r):   # the top pages' text too, fetched at once: one search usually answers it, no extra read rounds
        try:
            return text_of(get(r[1], timeout=1.5))[:1200]
        except Exception:
            return ''
    from concurrent.futures import ThreadPoolExecutor
    for r, txt in zip(out, ThreadPoolExecutor(3).map(page, out[:3])):
        r.append(txt and 'Page: ' + txt)
    return '\n\n'.join('\n'.join(filter(None, r)) for r in out) or 'no results (DuckDuckGo may be blocking; use WebSearch)'


WEB_JS = os.path.join(os.path.dirname(paths.ME), 'ui', 'web.js')


RISKY_CLICK = (r'\b(send|post|publish|delete|remove|trash|buy|purchase|pay|checkout|order|unsubscribe|confirm|submit|complete|finish|'
               r'accept|agree|yes|ok|continue|subscribe|cancel|transfer|submits a form)\b')   # words that hide a send/delete/buy count too


def browser_terms(app, adapter, window=None, tab=None):
    """AppleScript protocol adapters selected by a live JavaScript probe, never by an app-name list."""
    quoted = app.replace('\\', '\\\\').replace('"', '\\"')
    current = 'id of active tab' if adapter == 'chromium' else 'index of current tab'
    target = (f'execute (first tab of window id {window} whose id is {tab}) javascript (item 1 of argv)' if adapter == 'chromium'
              else f'do JavaScript (item 1 of argv) in tab {tab} of window id {window}')
    query = f'tell application "{quoted}"\nif (count windows) is 0 then error "No browser windows; use hands"\nreturn (id of window 1 as text) & (ASCII character 9) & ({current} of window 1 as text)\nend tell'
    tell = f'tell application "{quoted}" to {target}'
    return query, tell


def browser_adapter(app):
    """Return the page-JavaScript protocol an app actually answers, cached by bundle id."""
    try:
        if subprocess.run(['pgrep', '-xq', app], capture_output=True, timeout=.3).returncode:
            return ''
    except (OSError, subprocess.TimeoutExpired):
        return ''
    try:
        quoted = app.replace('\\', '\\\\').replace('"', '\\"')
        r = subprocess.run(['osascript', '-e', f'id of application "{quoted}"'],
                           capture_output=True, text=True, timeout=.3)
        key = r.stdout.strip() if not r.returncode and isinstance(r.stdout, str) and r.stdout.strip() else app
    except (OSError, subprocess.TimeoutExpired):
        key = app
    cache_path = os.path.join(paths.DIR, 'web-capabilities.json')
    try:
        with open(cache_path) as f: cached = json.load(f)
        if cached.get(key) in ('chromium', 'webkit'): return cached[key]
        if cached.get(key) is False: return ''
    except (OSError, ValueError, AttributeError): cached = {}
    def remember(value):
        os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
        cached[key] = value
        with tempfile.NamedTemporaryFile(mode='w', dir=paths.DIR, delete=False) as f:
            json.dump(cached, f); name = f.name
        os.chmod(name, 0o600); os.replace(name, cache_path)
    try:
        with open(WEB_JS) as f: src = f.read()
    except OSError:
        return ''
    probe = f'({src})("ready", "", "")'
    uncertain = False
    permission_error = re.compile(r'-1743|not authorized|not allowed', re.I)
    for adapter in ('chromium', 'webkit'):
        query, _ = browser_terms(app, adapter)
        try:
            target = subprocess.run(['osascript', '-e', query], capture_output=True, text=True, timeout=.5)
            ids = target.stdout.strip().split('\t') if isinstance(target.stdout, str) else []
            if target.returncode:
                uncertain = uncertain or bool(permission_error.search(target.stderr if isinstance(target.stderr, str) else ''))
                continue
            if len(ids) != 2 or not all(i.isdigit() for i in ids):
                uncertain = True
                continue
            _, tell = browser_terms(app, adapter, *map(int, ids))
            answer = subprocess.run(['osascript', '-e', f'on run argv\n{tell}\nend run', probe],
                                    capture_output=True, text=True, timeout=.5)
            error = answer.stderr if isinstance(answer.stderr, str) else ''
            if answer.returncode and 'javascript' not in error.lower():
                uncertain = uncertain or bool(permission_error.search(error))
                continue
            if not answer.returncode:
                state = json.loads(answer.stdout if isinstance(answer.stdout, str) else '')
                if not isinstance(state, dict) or 'ready' not in state: continue
            remember(adapter)
            return adapter
        except (OSError, ValueError, subprocess.TimeoutExpired):
            uncertain = True
            continue
    if not uncertain: remember(False)
    return ''


def close_agent_window(directory):
    """Task end: close the window the agent opened (never one it found), without launching the browser."""
    path = os.path.join(paths.agent_gate_dir(directory), 'browser-window.json')
    try:
        with open(path) as f: saved = json.load(f)
        os.remove(path)
        app, window = saved['app'], saved['window']
        if type(window) is not int or not isinstance(app, str) or subprocess.run(['pgrep', '-xq', app], timeout=.5).returncode: return
        quoted = app.replace('\\', '\\\\').replace('"', '\\"')
        subprocess.run(['osascript', '-e', f'tell application "{quoted}" to if exists window id {window} then close window id {window}'], capture_output=True, timeout=3)
    except (KeyError, OSError, ValueError, AttributeError, subprocess.TimeoutExpired): pass


def work_page(app='', words='', ask=''):
    """The user's open window a handed-off ask works in, so its agent acts there and nowhere else: the page this ask already
    used, else app's tab whose title or URL has the words, else its front tab; other apps: the front window's title. {} if none."""
    try:
        with open(os.path.join(ask, 'web.json')) as f: used = json.load(f)
        used = {k: used[k] for k in ('app', 'adapter', 'window', 'tab')} if isinstance(used.get('app'), str) and all(type(used.get(k)) is int for k in ('window', 'tab')) else {}
    except (OSError, ValueError, AttributeError, KeyError): used = {}
    reuse = bool(used) and (not app or used['app'] == app and not words)
    if not app and not reuse: return {}
    app = used['app'] if reuse else app
    adapter = used['adapter'] if reuse else browser_adapter(app)
    if not adapter:
        title = macos.osa(f'tell application "System Events" to tell process "{macos.osa_quote(apps.proc_of(app))}" to get name of front window', timeout=2)
        try:   # the user's other windows of the app at ask time (native hands): the agent's hands stay out of them too
            with open(paths.hands_state() + '.windows') as f: windows = json.load(f)
        except (OSError, ValueError): windows = None
        return {'app': app, **({'title': title} if title else {}), **({'windows': windows} if isinstance(windows, dict) else {})}
    title, active, tab_id, pinned = (('title', 'active tab', 'id', 'first tab of w whose id is ((item 3 of argv) as integer)') if adapter == 'chromium' else
                                     ('name', 'current tab', 'index', 'tab ((item 3 of argv) as integer) of w'))
    row = f'return (id of w as text) & (ASCII character 9) & ({tab_id} of t as text) & (ASCII character 9) & {title} of t & (ASCII character 9) & URL of t'
    found = macos.osa(f'on run argv\ntell application "{macos.osa_quote(app)}"\nif (item 2 of argv) is not "" then\nset w to window id ((item 2 of argv) as integer)\nset t to {pinned}\n{row}\nend if\n'
                f'if (item 1 of argv) is not "" then\nrepeat with w in windows\nrepeat with t in tabs of w\n'
                f'if ({title} of t contains item 1 of argv) or (URL of t contains item 1 of argv) then {row}\nend repeat\nend repeat\nend if\n'
                f'set w to window 1\nset t to {active} of w\n{row}\nend tell\nend run', words, *((str(used['window']), str(used['tab'])) if reuse else ('', '')), timeout=3).split('\t')   # a reused page's URL too: the agent acts only while it stays on that site
    if len(found) != 4 or not all(i.isdigit() and int(i) > 0 for i in found[:2]): return {'app': app}
    return {'app': app, 'adapter': adapter, 'window': int(found[0]), 'tab': int(found[1]), 'title': found[2][:200], 'url': found[3][:2000]}


def running_app(name):
    """The running app's exact name for a name the model wrote, as said ("chrome") or exact ('' when none runs)."""
    for n in dict.fromkeys(filter(None, (name, apps.app_named(name)))):
        try: found = (subprocess.run([paths.APP, '--target-app', n], capture_output=True, text=True, timeout=1).stdout or '').strip()
        except (OSError, subprocess.TimeoutExpired): continue
        if found: return found
    return ''


def page_ready(read, want=''):
    """Poll readiness and a stable DOM briefly; navigation errors are transient, permission errors are not.
    want: the host just opened; another tab that is already loaded must not count as ready."""
    host = lambda u: (urllib.parse.urlparse(u).hostname or '').removeprefix('www.')
    end = time.monotonic() + 5; previous = None; since = None
    while time.monotonic() < end:
        try: state = json.loads(read(min(0.5, max(0.01, end - time.monotonic()))))
        except (ValueError,subprocess.TimeoutExpired): state = {}
        except RuntimeError as e:
            if 'blocks this' in str(e): raise
            state = {}
        key = state.get('signature') if isinstance(state, dict) and state.get('ready') is True else None
        if key and want and host(key.split('|')[0]) != host(want): key = None
        now = time.monotonic()
        if key is not None and key == previous and since is not None and now - since >= 0.2: return True
        if key != previous or key is None: previous, since = key, now if key is not None else None
        time.sleep(min(0.1, max(0, end - now)))
    return False


def web(cmd, n='', text='', app=None, fresh=False, want='', page=None):
    """Drive the user's browser tab through its page, not the screen: read it (numbered controls), click or fill by number.
    Faster and surer than screenshots + mouse clicks; the user's mouse and focus stay put."""
    if cmd == 'read' and str(n).startswith(('http:', 'https:')):
        try:
            url = urllib.parse.urlsplit(n)
            if not url.hostname or url.username or url.password: return 'Use an HTTP(S) page URL without credentials.'
        except ValueError: return 'Use a valid HTTP(S) page URL.'
        if not policy.agent_url_allowed(n): return policy.agent_url_denial()
        if prefs.pref('workIn', 'back') == 'front' and macos.wants_focus(None, True):
            status = show(n, bg=True)
            if not status.startswith('opened '): return status
            return web('read', app=app, want=n)
        try:
            app = app or running_app(n)
            adapter = browser_adapter(app) if app else ''
            if not adapter: return 'Open a scriptable browser window first. Background reads never launch or focus a browser.'
            quoted = app.replace('\\', '\\\\').replace('"', '\\"')
            tab_id = 'id of t' if adapter == 'chromium' else 'index of t'
            selection = 'active tab index' if adapter == 'chromium' else 'current tab'
            own = hands.agent_window(app) if environ.agent() else 0
            if environ.agent():   # the task's own window, reused for every page; the user's windows and tabs stay as they are
                opened = ('set w to make new window\nset URL of active tab of w to item 1 of argv\nset t to active tab of w' if adapter == 'chromium' else
                          'make new document with properties {URL:item 1 of argv}\nset w to window 1\nset t to current tab of w')
                selected = 'set active tab index of w to (count tabs of w)' if adapter == 'chromium' else 'set current tab of w to t'
                script = (f'on run argv\ntell application "{quoted}"\nset w to missing value\n'
                          'try\nset w to window id ((item 2 of argv) as integer)\nend try\n'
                          'if w is missing value then\nset prior to missing value\nif (count windows) > 0 then set prior to window 1\n'
                          f'{opened}\nif prior is not missing value then set index of prior to 1\nset made to "new"\n'
                          f'else\nset t to make new tab at end of tabs of w with properties {{URL:item 1 of argv}}\n{selected}\nset made to ""\nend if\n'
                          f'return (id of w as text) & (ASCII character 9) & ({tab_id} as text) & (ASCII character 9) & made\nend tell\nend run')
                mine = macos.osa('tell application "System Events" to get name of first process whose frontmost is true')
            else:
                script = (f'on run argv\ntell application "{quoted}"\n'
                          'if (count windows) is 0 then error "No browser window"\n'
                          f'set w to window 1\nset priorSelection to {selection} of w\n'
                          'set t to make new tab at end of tabs of w with properties {URL:item 1 of argv}\n'
                          f'set {selection} of w to priorSelection\n'
                          f'return (id of w as text) & (ASCII character 9) & ({tab_id} as text) & (ASCII character 9)\nend tell\nend run')
            r = subprocess.run(['osascript', '-e', script, n, str(own)], capture_output=True, text=True, timeout=5)
            ids = r.stdout.strip('\n').split('\t')
            if r.returncode or len(ids) != 3 or not all(i.isdigit() and int(i) > 0 for i in ids[:2]):
                return 'Could not create a background page in an existing window. Requested page was not read.'
            if ids[2] == 'new':
                storage.private_json(os.path.join(paths.agent_gate_dir(environ.ask_dir(required=True)), 'browser-window.json'), {'app': app, 'window': int(ids[0])})
                windows.keep_behind(mine, app, wait=.5)
            page = dict(app=app, adapter=adapter, window=int(ids[0]), tab=int(ids[1]), target=None)
            status = web('wait', text=n, app=app, page=page)
            if status != 'Page ready.': return status + '\nRequested page not ready; do not substitute another source.'
            result = web('read', app=app, want=n, page=page)
            directory = environ.ask_dir(paths.DIR)
            os.makedirs(directory, mode=0o700, exist_ok=True)
            storage.private_json(os.path.join(directory, 'web.json'), page)
            return result
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            return f'Could not read the background page: {e}'
    explicit = app; app = app or environ.front_app('')
    path = os.path.join(environ.ask_dir(paths.DIR), 'web.json')
    if page is None and not explicit and not fresh and (cmd != 'read' or environ.ask_dir()):
        try:
            with open(path) as f: prior = json.load(f)
            if isinstance(prior.get('app'), str): app = prior['app']
        except (OSError,ValueError,AttributeError): pass
    if not app:
        return 'No browser is open.'
    adapter = browser_adapter(app)
    if not adapter:
        return f'{app} does not expose a scriptable web page. Read it with {paths.WINDOW} or {paths.HANDS} see.'
    try:
        saved = page
        if saved is None and not fresh and os.path.exists(path) and (cmd != 'read' or environ.ask_dir()):
            with open(path) as f: saved = json.load(f)
        if not saved or saved.get('app') != app or saved.get('adapter') != adapter:
            query, _ = browser_terms(app, adapter)
            r = subprocess.run(['osascript', '-e', query], capture_output=True, text=True, timeout=5)
            ids = r.stdout.strip().split('\t')
            if r.returncode or len(ids) != 2 or not all(i.isdigit() for i in ids):
                return f'Could not find a scriptable page window. Use {paths.HANDS} see.'
            saved = {'app': app, 'adapter': adapter, 'window': int(ids[0]), 'tab': int(ids[1]), 'target': None}
            os.makedirs(os.path.dirname(path),mode=0o700,exist_ok=True)
            storage.private_json(path, saved)
        if not all(isinstance(saved.get(k), int) and saved[k] > 0 for k in ('window', 'tab')):
            raise ValueError('Invalid page target')
        if environ.agent() and cmd in ('click', 'fill', 'type-after') and saved['window'] != hands.agent_window(app):
            handed = hands.handed_page()
            if any(handed.get(k) != saved.get(k) for k in ('app', 'window', 'tab')):
                return f"That page is in the user's own window; agents only read it. To act on it, open its URL in this task's window: {paths.WEB} read <url>"
            want = want or handed.get('url', '')   # the user's tab went to another site: never act on that one
        if cmd in ('read','wait') or not saved.get('target'):
            r = subprocess.run(['osascript', '-e', f'tell application "{app}" to get {{name, bounds}} of window id {saved["window"]}'],capture_output=True,text=True,timeout=2)
            parts = r.stdout.strip().rsplit(', ',4)
            if r.returncode or len(parts) != 5: raise ValueError('Could not locate the pinned page window')
            l,t,right,bottom = map(float,parts[1:])
            saved['target'] = macos.preview_app(app, cmd, title=parts[0], frame=[l,t,right-l,bottom-t])
            if cmd == 'read' and not n: hands.hands_map(app, saved['target'])
            if page is None: storage.private_json(path, saved)
        _, tell = browser_terms(app, adapter, saved['window'], saved['tab'])
        if isinstance(saved.get('target'), dict): protocol.emit(['▣ ' + json.dumps({**saved['target'], 'action':cmd})])
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return f'Could not use the page: {e}\nUse the screen instead: {paths.HANDS} see'
    with open(WEB_JS) as f:
        src = f.read()
    def js(c, expr=None, timeout=15, again=True):
        r = subprocess.run(['osascript', '-e', f'on run argv\n{tell}\nend run', expr or f'({src})({json.dumps(c)}, {json.dumps(n)}, {json.dumps(text)})'],
                           capture_output=True, text=True, timeout=timeout)
        if again and 'turned off' in r.stderr and adapter == 'chromium' and interaction.allow_page_js(app, ask=True):
            return js(c, expr, timeout, False)
        if 'turned off' in r.stderr or 'not allowed' in r.stderr.lower():
            raise RuntimeError(f'{app} blocks this. Tell the user to turn on, once: ' + ('Safari > Develop > Allow JavaScript from Apple Events.' if app == 'Safari'
                               else f'{app} menu bar > View > Developer > Allow JavaScript from Apple Events.'))
        if r.returncode:
            raise RuntimeError(r.stderr.strip()[-300:] or 'the page did not answer')
        return r.stdout.strip()
    try:
        if cmd == 'wait': return 'Page ready.' if page_ready(lambda timeout:js('ready',timeout=timeout), text) else 'Page still loading. Read again before acting.'
        def same_source():
            state = json.loads(js('ready'))
            current = str(state.get('signature', '')).split('|')[0]
            host = lambda url: (urllib.parse.urlsplit(url).hostname or '').removeprefix('www.')
            return host(current) == host(want)
        if want and not same_source(): return 'The browser is not on the requested source. Read it again before continuing.'
        if cmd == 'click':
            try:
                c = json.loads(js('name'))
            except ValueError:
                return 'No such control. Read the page again.'
            if c.get('submit') or re.search(RISKY_CLICK, c['what'], re.I) and prefs.pref('safe', True):
                if not environ.ask_dir():   # a saved shortcut has no Allow card: never click these blind
                    return 'This click needs the user\'s confirmation. Ask through Rabik, not a shortcut.'
                if not policy.task_allowed('web click'):
                    answer = interaction.ask_user({'q': f'Click "{c["short"][:40]}"?', 'cmd': f'{app}: click "{c["what"][:300]}"', 'task': policy.managed_agent()}, 60)
                    if answer == 'task' and policy.managed_agent(): policy.allow_for_task('web click')
                    elif answer != 'y': return 'The user said no. Do not try another way; say it was not done.'
            if json.loads(js('name')) != c:
                return 'The control changed since the check. Read the page again.'
            text = c['url']   # click only in the tab that was checked
            done = js('click')
            if not done.startswith('Clicked'): return done
            try:
                if not page_ready(lambda timeout:js('ready',timeout=timeout)): return done + '\nPage still loading. Read again before acting.'
                changed = js('state')
                try: state = json.loads(changed)
                except ValueError: state = {'target': {'label': c['short'], 'status': changed}, 'page': json.loads(js('ready'))}
                return done + '\nChanged state:\n' + json.dumps(state, ensure_ascii=False)
            except (RuntimeError,ValueError,subprocess.TimeoutExpired):
                return done + '\nPage readiness unavailable. Read again before acting.'   # the click succeeded; never report it failed and cause a duplicate
        result = js(cmd if cmd in ('read', 'fill', 'type-after') else 'read')
        if want and not same_source(): return 'The page left the requested source during the read. Its content was not returned.'
        if cmd == 'type-after':
            return result
        if cmd == 'fill' and result.startswith('Filled'):
            try:
                if not page_ready(lambda timeout: js('ready', timeout=timeout)):
                    return result + '\nPage still loading. Re-read values before claiming success.'
                return result + '\nChanged state:\n' + js('state')
            except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                return result + '\nChanged state unavailable. Re-read values before claiming success.'
        return result
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        return f'Could not use the page: {e}\nUse the screen instead: {paths.HANDS} see'   # e.g. a second, windowless Chrome took the AppleScript


def connectors():
    """The user's claude.ai connectors: names connected, and names that need a sign-in."""
    claude = environ.claude() or shutil.which('claude') or os.path.expanduser('~/.local/bin/claude')
    try: out = subprocess.run([claude, 'mcp', 'list'], capture_output=True, text=True, timeout=20, cwd=tempfile.gettempdir(),
                              env={k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}).stdout
    except (OSError, subprocess.TimeoutExpired): out = ''
    rows = re.findall(r'^claude\.ai (.+?): \S+ - (.+)$', out, re.M)
    return {'connected': [n for n, state in rows if 'Connected' in state], 'signin': [n for n, state in rows if 'Connected' not in state]}
