"""People: who the user met and what Rabik knows about them, built each time from the saved meetings (calendar attendees and
speaker names) and About you's People facts. Nothing new is stored; hiding a person keeps them out (peopleHidden)."""
import re
from datetime import datetime
from brain import meeting, memory, prefs, sources

__all__ = ['PEOPLE_NOT_NAMES', 'person_key', 'people_all', 'people_find', 'people_command']


PEOPLE_NOT_NAMES = {'you', 'them', 'room', 'someone', 'someone else', 'demo', 'call', 'unknown'}


def person_key(person):
    return (person.get('email') or ' '.join(str(person.get('name', '')).split())).casefold()


def people_all():
    """Everyone, most recently met first: {id, name, email, last, meetings: [{id, title, started}], facts}."""
    found = {}   # key -> person
    def add(name, email='', met=None, fact=None):
        name, email = ' '.join(str(name).split())[:80], str(email).strip().casefold()[:120]
        if not name or name.casefold() in PEOPLE_NOT_NAMES or '@' in name: return
        key = email or name.casefold()
        p = found.setdefault(key, {'name': name, 'email': email, 'last': 0, 'meetings': {}, 'facts': []})
        if len(name) > len(p['name']): p['name'] = name   # "Sam Lee" over "Sam"
        if met: p['meetings'][met['id']] = met; p['last'] = max(p['last'], met['started'])
        if fact and fact not in p['facts']: p['facts'].append(fact)
    for row in meeting.meeting_list():
        try: m = meeting.meeting_read(row['id'])
        except (OSError, ValueError, KeyError, TypeError): continue
        met = {'id': row['id'], 'title': m.get('title') or 'Meeting', 'started': m['started']}
        for a in m.get('people') or []:
            if isinstance(a, dict): add(a.get('name', ''), a.get('email', ''), met)
        for r in m['transcript']:
            if not r.get('mic') and r.get('speaker') not in (m.get('app'), None) and not r.get('recovered'): add(r['speaker'], met=met)
    # One person, many spellings: the same name with and without an email, and a first name only one full name starts with.
    for key, p in list(found.items()):
        if p['email']: continue
        same = [q for k, q in found.items() if k != key and (q['name'].casefold() == p['name'].casefold()
                or (' ' not in p['name'] and q['name'].casefold().split()[0] == p['name'].casefold()))]
        if len(same) == 1:
            q = same[0]; q['meetings'].update(p['meetings']); q['last'] = max(q['last'], p['last']); q['facts'] += [f for f in p['facts'] if f not in q['facts']]
            del found[key]
    for f in memory.me()['facts']:
        if f['category'] != 'people' or f.get('sensitive'): continue
        text = f"{f['kind']}: {f['value']}" if f['kind'] else f['value']
        owners = [p for p in found.values() if any(re.search(r'\b' + re.escape(part) + r'\b', text, re.I) for part in {p['name'], p['name'].split()[0]})]
        if owners: [p['facts'].append(text) for p in owners if text not in p['facts']]
        elif re.fullmatch(r"[A-ZÇĞİÖŞÜ][\w'’-]+(?: [A-ZÇĞİÖŞÜ][\w'’-]+){0,2}", f['kind'] or ''): add(f['kind'], fact=f['value'])
    hidden = {str(h).casefold() for h in prefs.pref('peopleHidden', []) or []}
    people = []
    for p in found.values():
        p['id'] = person_key(p)
        if p['id'] in hidden: continue
        p['meetings'] = sorted(p['meetings'].values(), key=lambda m: m['started'], reverse=True)[:10]
        people.append(p)
    return sorted(people, key=lambda p: (p['last'], p['name']), reverse=True)


def people_find(words):
    """--people "<name>": who they are, when the user last met them and in which meetings; the person becomes a source chip."""
    want = [w for w in re.findall(r'[\w-]+', words.casefold()) if w not in ('with', 'about', 'last', 'talk', 'talked', 'met', 'who', 'is')]
    people = [p for p in people_all() if want and any(w in p['name'].casefold().split() or w == p['email'] for w in want)]
    if not people: return 'Nobody by that name in meetings or About you.'
    lines = []
    for p in people[:3]:
        sources.source_note('person', p['id'], p['name'])
        lines.append(p['name'] + (f" <{p['email']}>" if p['email'] else ''))
        if p['last']: lines.append('Last met: ' + datetime.fromtimestamp(p['last']).strftime('%a %Y-%m-%d'))
        for m in p['meetings'][:5]: lines.append(f"- Meeting: {m['title']} ({datetime.fromtimestamp(m['started']).strftime('%Y-%m-%d')}); read it with --meeting-history \"{m['title']}\"")
        lines += ['- Known: ' + f for f in p['facts'][:8]]
        lines.append('')
    return '\n'.join(lines).strip()


def people_command(args):
    """--people list (Settings, JSON) | --people "<name>" (an ask)."""
    if args == ['list']:
        return {'people': [{**p, 'meetings': p['meetings'][:10]} for p in people_all()]}
    return people_find(' '.join(args))
