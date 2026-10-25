"""What Rabik keeps about the user: the About-you profile (me.json), the saved rules (memory.md), the last few turns
of chat (recent.jsonl) and the request history search."""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from functools import wraps
from brain import environ, paths, storage, wording

__all__ = ['ME_FILE', 'CATEGORIES', 'SOURCES', 'SENSITIVE', 'category', '_profile_date', '_mask', '_fact', '_PROFILE_MUTEX',
           '_PROFILE_STATE', '_profile_locked', '_save_profile', '_normalize_profile', 'me', 'profile_name',
           '_is_answer_preference', '_answer_preferences', 'me_line', 'profile_context', 'profile_category', '_request_contains',
           '_split_fact', 'profile_add', 'profile_set', 'profile_drop', 'profile_forget_source', 'mac_profile', 'profile_import',
           '_MEMORY_MUTEX', '_MEMORY_STATE', '_memory_locked', 'memory_rules', '_save_memory_rules', 'remember_rule', 'edit_rule',
           'forget_rules', 'memory_find', 'relevant_rules', 'memory_items', 'memory_receipt', 'recent', 'earlier_chat',
           'remember_turn', 'history']


# About the user. Only a short name/answer-style line is always sent; category facts are attached when their
# labels match the request or visible form. One writer: rabik.py's --me commands.
ME_FILE = os.path.join(paths.DIR, 'me.json')


CATEGORIES = {
    'basics': 'Basics', 'contact': 'Contact', 'places': 'Places', 'school_work': 'School & work',
    'links': 'Links & handles', 'preferences': 'Preferences', 'people': 'People', 'notes': 'Notes',
}


SOURCES = ('you', 'contacts', 'mail', 'learned')


SENSITIVE = re.compile(r'\b(ssn|social security|credit card|debit card|card number|cvv|password|passcode|pin|health|medical|money|income|salary|bank|routing)\b', re.I)


def category(value):
    key = re.sub(r'[^a-z]+', '_', str(value).lower()).strip('_')
    return {'basic': 'basics', 'school': 'school_work', 'work': 'school_work', 'school_and_work': 'school_work',
            'links_handles': 'links', 'link': 'links', 'handle': 'links', 'preference': 'preferences',
            'person': 'people', 'note': 'notes'}.get(key, key if key in CATEGORIES else 'notes')


def _profile_date():
    return time.strftime('%Y-%m-%d')


def _mask(value):
    tail = ''.join(re.findall(r'\w', value, re.UNICODE))[-4:]
    return '••••' + (f' {tail}' if tail else '')


def _fact(category_, kind, value, source='you', date=None, identifier=None, sensitive=None):
    if value is None:
        return None
    category_, kind, value = category(category_), ' '.join(str(kind or '').split())[:40] or 'note', ' '.join(str(value).split())[:300]
    if not value:
        return None
    private = bool(sensitive) or bool(SENSITIVE.search(kind + ' ' + value))
    if private and not value.startswith('••••'):
        value = _mask(value)
    source = source if source in SOURCES else 'you'
    key = '\0'.join((source, category_, kind.lower(), value.lower()))
    return {'id': identifier or hashlib.sha256(key.encode()).hexdigest()[:12], 'category': category_, 'kind': kind,
            'value': value, 'source': source, 'date': date if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(date or '')) else _profile_date(),
            **({'sensitive': True} if private else {})}


_PROFILE_MUTEX = threading.RLock()


_PROFILE_STATE = threading.local()


def _profile_locked(operation):
    @wraps(operation)
    def locked(*args, **kwargs):
        with _PROFILE_MUTEX:
            if getattr(_PROFILE_STATE, 'locked', False):
                return operation(*args, **kwargs)
            os.makedirs(os.path.dirname(ME_FILE), mode=0o700, exist_ok=True)
            with open(ME_FILE + '.lock', 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                _PROFILE_STATE.locked = True
                try:
                    return operation(*args, **kwargs)
                finally:
                    _PROFILE_STATE.locked = False
    return locked


def _save_profile(profile):
    folder = os.path.dirname(ME_FILE)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=folder, delete=False) as f:
        try:
            json.dump({'version': 2, 'facts': profile['facts']}, f, indent=1, ensure_ascii=False)
            f.flush(); os.fchmod(f.fileno(), 0o600); os.replace(f.name, ME_FILE)
        finally:
            if os.path.exists(f.name):
                os.unlink(f.name)


def _normalize_profile(raw, legacy_date=None):
    if isinstance(raw, dict) and raw.get('version') == 2 and isinstance(raw.get('facts'), list):
        facts = [_fact(f.get('category'), f.get('kind'), f.get('value'), f.get('source'), f.get('date'),
                       f.get('id'), f.get('sensitive')) for f in raw['facts'] if isinstance(f, dict)]
        profile = {'version': 2, 'facts': [f for f in facts if f]}
        return profile, profile != {'version': 2, 'facts': raw['facts']}
    facts = []
    if isinstance(raw, dict):
        if raw.get('name'):
            facts.append(_fact('basics', 'name', raw['name'], 'you', legacy_date))
        if raw.get('about'):
            facts.append(_fact('notes', 'about', raw['about'], 'you', legacy_date))
        facts.extend(_fact('notes', 'fact', value, 'learned', legacy_date) for value in raw.get('facts', []) if value)
    return {'version': 2, 'facts': [f for f in facts if f]}, isinstance(raw, dict)


@_profile_locked
def me():
    try:
        with open(ME_FILE) as f:
            raw = json.load(f)
        legacy_date = time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(ME_FILE)))
    except (OSError, ValueError):
        return {'version': 2, 'facts': []}
    profile, migrated = _normalize_profile(raw, legacy_date)
    if migrated:
        try:
            _save_profile(profile)
        except OSError:
            pass
    return profile


def profile_name(profile=None):
    facts = (profile or me())['facts']
    names = [f for f in facts if f['category'] == 'basics' and f['kind'].lower() == 'name' and not f.get('sensitive')]
    return next((f['value'] for source in SOURCES for f in names if f['source'] == source), '')


def _is_answer_preference(fact):
    return fact['category'] == 'preferences' and bool(wording._words(fact['kind']) & {'answer', 'response', 'reply', 'writing', 'style'})


def _answer_preferences(profile):
    return [f['value'] for f in profile['facts'] if _is_answer_preference(f) and not f.get('sensitive')]


def me_line(profile=None):
    profile = profile or me()
    parts = ([f'Name: {profile_name(profile)}.'] if profile_name(profile) else []) + \
            ([f"Answer preference: {_answer_preferences(profile)[0].rstrip('.')}."] if _answer_preferences(profile) else [])
    return ' '.join(parts)[:300]


def profile_context(task='', screen='', profile=None):
    provided = profile is not None
    profile = profile or me()
    safe = [f for f in profile['facts'] if not f.get('sensitive')]
    seen = wording._words(task + '\n' + screen)
    relevant = set()
    for f in safe:
        keys = wording._words(f['kind'])
        category_keys = wording._words(f['category'].replace('_', ' ') + ' ' + CATEGORIES[f['category']])
        if seen & keys or seen & category_keys or f['category'] == 'people' and seen & wording._words(f['value']):
            relevant.add(f['category'])
    always = me_line(profile) if provided else me_line()
    lines = [f'About you: {always}'] if always else []
    for key in CATEGORIES:
        facts = [f for f in safe if f['category'] == key and
                 not (key == 'basics' and f['kind'].lower() == 'name') and
                 not _is_answer_preference(f)]
        if key in relevant and facts:
            lines.append(CATEGORIES[key] + ': ' + '; '.join(f"{f['kind']}: {f['value']}" for f in facts))
    return '\n'.join(lines)


def profile_category(name):
    key, profile = category(name), me()
    facts = [f for f in profile['facts'] if f['category'] == key and not f.get('sensitive')]
    return CATEGORIES[key] + ':\n' + ('\n'.join(f"- {f['kind']}: {f['value']} [{f['id']}]" for f in facts) or 'Nothing saved.')


def _request_contains(evidence):
    """The user said these words: in this ask, or in a question of this chat ("remember that" points back). Never the AI's answers."""
    root = environ.ask_dir()
    if not root:
        return True
    try:
        with open(paths.request_file(root)) as f:
            said = [f.read()]
    except OSError:
        said = []
    said += [r['q'] for r in recent() if time.time() - r['t'] < 600][-3:]   # the same turns the AI sees as Earlier
    needle = ' '.join(re.findall(r'\w+', evidence.lower()))
    return bool(needle) and any(f' {needle} ' in ' ' + ' '.join(re.findall(r'\w+', q.lower())) + ' ' for q in said)


def _split_fact(text, fallback):
    match = re.match(r'\s*([^:=]{1,40})\s*[:=]\s*(.+)', text)
    return (match[1].strip(), match[2].strip()) if match else (fallback, text.strip())


@_profile_locked
def profile_add(category_, text, kind='', source=None):
    profile, category_ = me(), category(category_)
    source = source or ('learned' if environ.ask_dir() else 'you')
    if source == 'learned' and not _request_contains(text):
        return 'not saved: only the user’s own words can change About you'
    kind, value = (kind, text.strip()) if kind else _split_fact(text, CATEGORIES[category_].rstrip('s').lower())
    private = bool(SENSITIVE.search(kind + ' ' + value))
    if source == 'learned' and private:
        return 'not saved: sensitive facts are never learned'
    fact = _fact(category_, kind, value, source, sensitive=private)
    if not fact:
        return 'not saved: empty fact'
    duplicate = next((f for f in profile['facts'] if all(f.get(k) == fact.get(k) for k in ('category', 'kind', 'value', 'source'))), None)
    if not duplicate:
        profile['facts'].append(fact); _save_profile(profile)
    return 'saved'


@_profile_locked
def profile_set(identifier, text, evidence=None):
    if environ.ask_dir() and not _request_contains(evidence if evidence is not None else text):
        return 'not saved: only the user’s own words can change About you'
    profile = me()
    fact = next((f for f in profile['facts'] if f['id'] == identifier), None)
    if not fact:
        return 'not found'
    kind, value = _split_fact(text, fact['kind'])
    changed = _fact(fact['category'], kind, value, 'learned' if environ.ask_dir() else 'you',
                    identifier=identifier, sensitive=bool(SENSITIVE.search(kind + ' ' + value)))
    if not changed:
        return 'not saved: empty fact'
    profile['facts'][profile['facts'].index(fact)] = changed; _save_profile(profile)
    return 'saved'


@_profile_locked
def profile_drop(identifier, evidence=''):
    if environ.ask_dir() and not _request_contains(evidence):
        return 'not forgotten: only the user’s own words can change About you'
    profile = me()
    kept = [f for f in profile['facts'] if f['id'] != identifier]
    if len(kept) == len(profile['facts']):
        return 'not found'
    profile['facts'] = kept; _save_profile(profile)
    return 'forgotten'


@_profile_locked
def profile_forget_source(source, evidence=''):
    if environ.ask_dir() and not _request_contains(evidence):
        return 'not forgotten: only the user’s own words can change About you'
    if source not in SOURCES:
        return 'not found'
    profile = me(); before = len(profile['facts'])
    profile['facts'] = [f for f in profile['facts'] if f['source'] != source]
    _save_profile(profile)
    return f'forgotten {before - len(profile["facts"])}'


def mac_profile():
    """Read Contacts My Card and Mail accounts only when Settings explicitly invokes import."""
    script = r'''function run() {
function failed(e) { if(out.errors.indexOf(source)<0) out.errors.push(source); if(out.errorReasons[source]!=="automation") out.errorReasons[source]=Number(e.errorNumber || e.number)===-1743 ? "automation" : "read"; }
function safe(f,d) { try { var v=f(); return v === null || v === undefined ? d : v; } catch(e) { failed(e); return d; } }
function pairs(xs) { return safe(()=>xs().map(x=>({label:safe(()=>x.label(),""),value:safe(()=>x.value(),"")})),[]); }
var out={contacts:null,mail:null,errors:[],errorReasons:{}}, source="contacts";
try {
  var app=Application("Contacts"), p=app.myCard(), birthday=safe(()=>p.birthDate(),null);
  out.contacts={
    name:safe(()=>p.name(),""),
    pronouns:safe(()=>p.pronouns(),""),
    birthday:birthday && birthday.toISOString ? birthday.toISOString().slice(0,10) : birthday || "",
    emails:pairs(()=>p.emails()), phones:pairs(()=>p.phones()), urls:pairs(()=>p.urls()),
    addresses:safe(()=>p.addresses().map(x=>{var v=x.value();return {label:safe(()=>x.label(),"address"),value:[v.street,v.city,v.state,v.zip,v.country].filter(Boolean).join(", ")}}),[]),
    organization:safe(()=>p.organization(),""), department:safe(()=>p.department(),""),
    jobTitle:safe(()=>p.jobTitle(),""),
    social:safe(()=>p.socialProfiles().map(x=>{var v=x.value();return {label:v.service || "social",value:v.url || v.username || v.userIdentifier || ""}}),[]),
    related:pairs(()=>p.relatedNames())
  };
} catch(e) { failed(e); }
try {
  source="mail"; var mail=Application("Mail");
  out.mail=safe(()=>mail.accounts().map(a=>({name:safe(()=>a.name(),""),emails:safe(()=>a.emailAddresses(),[])})),[]);
} catch(e) { failed(e); }
return JSON.stringify(out);
}'''
    try:
        result = subprocess.run(['osascript', '-l', 'JavaScript', '-e', script], capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise ValueError(result.stderr)
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError('invalid import')
        return data
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'contacts': None, 'mail': None, 'errors': ['contacts', 'mail']}


@_profile_locked
def profile_import(snapshot=None):
    data, profile = snapshot if snapshot is not None else mac_profile(), me()
    incoming, refreshed = [], set()
    contacts_data = data.get('contacts') if isinstance(data, dict) else None
    if isinstance(contacts_data, dict) and 'contacts' not in data.get('errors', []):
        refreshed.add('contacts')
        def add(category_, kind, value):
            fact = _fact(category_, kind, value, 'contacts')
            if fact:
                incoming.append(fact)
        add('basics', 'name', contacts_data.get('name'))
        add('basics', 'birthday', contacts_data.get('birthday'))
        add('basics', 'pronouns', contacts_data.get('pronouns'))
        for item in contacts_data.get('emails', []):
            add('contact', ((item.get('label') or '') + ' email').strip(), item.get('value'))
        for item in contacts_data.get('phones', []):
            add('contact', ((item.get('label') or '') + ' phone').strip(), item.get('value'))
        for item in contacts_data.get('addresses', []):
            add('places', ((item.get('label') or '') + ' address').strip(), item.get('value'))
        for key, label in [('organization', 'organization'), ('department', 'department'), ('jobTitle', 'job title')]:
            add('school_work', label, contacts_data.get(key))
        for item in contacts_data.get('urls', []):
            add('links', item.get('label') or 'url', item.get('value'))
        for item in contacts_data.get('social', []):
            add('links', item.get('label') or 'social', item.get('value'))
        for item in contacts_data.get('related', []):
            add('people', item.get('label') or 'relation', item.get('value'))
    mail_data = data.get('mail') if isinstance(data, dict) else None
    if isinstance(mail_data, list) and 'mail' not in data.get('errors', []):
        refreshed.add('mail')
        for account in mail_data:
            if not isinstance(account, dict):
                continue
            account_fact = _fact('contact', 'mail account', account.get('name'), 'mail')
            if account_fact:
                incoming.append(account_fact)
            for address in account.get('emails', []):
                fact = _fact('contact', ((account.get('name') or '') + ' email').strip() or 'email', address, 'mail')
                if fact:
                    incoming.append(fact)
    if refreshed:
        profile['facts'] = [f for f in profile['facts'] if f['source'] not in refreshed]
        seen = {(f['source'], f['category'], f['kind'].lower(), f['value'].lower()) for f in profile['facts']}
        for fact in incoming:
            key = (fact['source'], fact['category'], fact['kind'].lower(), fact['value'].lower())
            if key not in seen:
                profile['facts'].append(fact); seen.add(key)
        _save_profile(profile)
    counts = {source: sum(f['source'] == source for f in profile['facts']) for source in SOURCES}
    return {'counts': counts, 'imported': len(incoming), 'errors': data.get('errors', []) if isinstance(data, dict) else ['contacts', 'mail'],
            'errorReasons': data.get('errorReasons', {}) if isinstance(data, dict) else {}}


def history(words):
    """Past asks that match, best first: "what was that link yesterday", "do what I did Monday again". Words or a date (2026-10-10)."""
    want = [w for w in re.findall(r'[\w-]+', words.lower()) if len(w) > 2]
    rows = [r for r in storage.read_rows(os.path.join(paths.DIR, 'log.jsonl')) if isinstance(r.get('task'), str) and r.get('reply')]
    hay = lambda r: ' '.join([r.get('at', ''), r['task'], str(r.get('reply', '')), ' '.join(r.get('ran') or [])]).lower()
    hits = sorted(((sum(w in hay(r) for w in want), i, r) for i, r in enumerate(rows)), key=lambda h: h[:2], reverse=True)
    hits = [r for score, _, r in hits if score or not want][:6]
    return '\n'.join(f"{r.get('at', '')[:16]} asked: {r['task'][:200]} -> {str(r['reply'])[:300]}" +
                     (f" [ran: {'; '.join(r['ran'])[:200]}]" if r.get('ran') else '') for r in hits) or 'Nothing matches.'


_MEMORY_MUTEX = threading.RLock()


_MEMORY_STATE = threading.local()


def _memory_locked(operation):
    @wraps(operation)
    def locked(*args, **kwargs):
        with _MEMORY_MUTEX:
            if getattr(_MEMORY_STATE, 'locked', False):
                return operation(*args, **kwargs)
            os.makedirs(os.path.dirname(paths.MEMORY), mode=0o700, exist_ok=True)
            with open(paths.MEMORY + '.lock', 'a') as lock:
                os.chmod(paths.MEMORY + '.lock', 0o600)
                fcntl.flock(lock, fcntl.LOCK_EX)
                _MEMORY_STATE.locked = True
                try:
                    return operation(*args, **kwargs)
                finally:
                    _MEMORY_STATE.locked = False
    return locked


def memory_rules():
    try:
        with open(paths.MEMORY) as f:
            return [line.removeprefix('- ').strip() for line in f if line.removeprefix('- ').strip()]
    except OSError:
        return []


def _save_memory_rules(rules):
    folder = os.path.dirname(paths.MEMORY)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=folder, delete=False) as f:
        try:
            f.writelines('- ' + rule + '\n' for rule in rules)
            f.flush(); os.fchmod(f.fileno(), 0o600); os.replace(f.name, paths.MEMORY)
        finally:
            if os.path.exists(f.name):
                os.unlink(f.name)


@_memory_locked
def remember_rule(text):
    text = ' '.join(str(text).split())
    if not text:
        return 'not saved: empty rule'
    rules = memory_rules()
    if text.casefold() not in {rule.casefold() for rule in rules}:
        rules.append(text)
        _save_memory_rules(rules)
    return 'saved'


@_memory_locked
def edit_rule(old, new):
    old, new = old.strip(), ' '.join(str(new).split())
    rules = [new if rule == old and new else rule for rule in memory_rules() if rule != old or new]
    _save_memory_rules(rules)
    return 'saved'


@_memory_locked
def forget_rules(query):
    words = ' '.join(str(query).split()).casefold().split()
    if not words:
        return 0
    rules = memory_rules()
    exact = [rule for rule in rules if rule.casefold() == ' '.join(words)]
    kept = [rule for rule in rules if rule not in exact] if exact else [rule for rule in rules if not all(word in rule.casefold() for word in words)]
    _save_memory_rules(kept)
    return len(rules) - len(kept)


def memory_find(query=''):
    """Search both user-memory stores without making the model guess a profile category."""
    words = wording._words(query) - wording.STOP
    matches = lambda text: not words or bool(words & wording._words(text))
    facts = [f for f in me()['facts'] if not f.get('sensitive') and
             (matches(f['category'].replace('_', ' ') + ' ' + CATEGORIES[f['category']]) or
              matches(f['kind']) or matches(f['value']))]
    rules = [rule for rule in memory_rules() if matches(rule)]
    lines = []
    for key in CATEGORIES:
        found = [f for f in facts if f['category'] == key]
        if found:
            lines += [CATEGORIES[key] + ':'] + [f"- [{f['id']}] {f['kind']}: {f['value']}" for f in found]
    if rules:
        lines += ['Rules:'] + ['- ' + rule for rule in rules]
    return '\n'.join(lines)[:8000] or 'Nothing matches.'


def relevant_rules(task, most=15):
    """All saved rules while they fit in ~4000 chars ("email Robert" needs the "dad" rule); past that, up to `most` that share a word with the request."""
    rules = memory_rules()
    if sum(map(len, rules)) < 4000:
        return '\n'.join(rules)
    words = set(re.findall(r'[a-z0-9]+', task.lower())) - wording.STOP
    hits = [r for r in rules if words & set(re.findall(r'[a-z0-9]+', r.lower()))]
    return '\n'.join(hits[:most])


def recent():
    return [r for r in storage.read_rows(paths.RECENT) if isinstance(r.get('t'), (int, float)) and
            isinstance(r.get('q'), str) and isinstance(r.get('a'), str)]


def earlier_chat(turns):
    """Recent Q/A for follow-ups; the last answer whole: a cut draft got rewritten on "insert it"."""
    return ''.join(f'Q: {r["q"]}\nA: {r["a"][:1000 if r is not turns[-1] else 4000]}\n' for r in turns)


def memory_items():
    """What Settings → Memory lists, as (category, text): profile facts by category, and saved rules under 'rules'."""
    rules = memory_rules()
    return {('rules', r) for r in rules if r} | {(f['category'], f"{f['kind']}: {f['value']}") for f in me()['facts']}


def memory_receipt(before):
    """The ask's memory changes for the box: [{c, label, t, add}], added first, in Settings order."""
    after, order = memory_items(), list(CATEGORIES) + ['rules']
    return [{'c': c, 'label': CATEGORIES.get(c, 'Rules'), 't': t, 'add': add}
            for add, items in ((True, after - before), (False, before - after)) for c, t in sorted(items, key=lambda i: (order.index(i[0]), i[1]))]


def remember_turn(q, a, shortcut=None, agents=()):
    turns = recent()
    turn = {'t': time.time(), 'q': q, 'a': a}
    if shortcut: turn['shortcut'] = shortcut
    if agents: turn['agents'] = list(agents)   # handoffIds: a follow-up about "them" finds the agents this turn started
    turns = [r for r in turns if time.time() - r['t'] < 600][-2:] + [turn]   # the same 10 min main() and _request_contains read
    os.makedirs(paths.DIR, mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=paths.DIR, delete=False) as f:
        try:
            f.writelines(json.dumps(r) + '\n' for r in turns); f.flush(); os.replace(f.name, paths.RECENT)
        finally:
            if os.path.exists(f.name): os.unlink(f.name)
