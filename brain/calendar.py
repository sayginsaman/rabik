"""Contacts and Calendar for the model (--contacts, --calendar): lookups, and edits only after the user approves."""
import json
import os
import re
import subprocess
import time
from brain import interaction, memory, paths, prompts, turn, wording

__all__ = ['contact_matches', 'contacts', 'calendar_backend', 'calendar_tool']


def contact_matches(query, cards, own):
    """Relationship labels come from the user's card, never from a name list."""
    def words(text): return set(re.findall(r'\w+', text.lower())) - wording.STOP
    related = [r['value'] for r in own.get('related', []) if words(query) and words(query) <= words(r['label'])]
    names = [query, *related]
    return [c for c in cards if any(words(n) and words(n) <= words(' '.join(str(c.get(k) or '') for k in ('name', 'nickname', 'organization'))) for n in names)]


def contacts(query):
    script = r'''function run(argv) {
var app = Application('Contacts'), people = app.people();
function related(p) { return p.relatedNames().map(x=>({label:x.label(), value:x.value()})); }
var own = {}; try { own = {name:app.myCard.name(), related:related(app.myCard())}; } catch(e) {}
if (!argv.length) {
    // Bulk properties: do not fetch every email/phone just to find one person.
    var names = app.people.name(), nicknames = app.people.nickname(), organizations = app.people.organization();
    return JSON.stringify({own:own, cards:names.map((n,i)=>({index:i, name:n || '', nickname:nicknames[i] || '', organization:organizations[i] || ''}))});
}
return JSON.stringify(JSON.parse(argv[0]).map(i=>({name:people[i].name(), emails:people[i].emails().map(x=>x.value()), phones:people[i].phones().map(x=>x.value())})));
}'''
    try:
        def read(*args):
            r = subprocess.run(['osascript', '-l', 'JavaScript', '-e', script, *args], capture_output=True, text=True, timeout=5)
            if r.returncode: raise ValueError(r.stderr.strip()[:300])
            return json.loads(r.stdout)
        data = read()
        matches = contact_matches(query, data['cards'], data['own'])
        matches = read(json.dumps([c['index'] for c in matches])) if matches else []
        return json.dumps({'matches': matches, 'ownCard': data['own'], 'profile': memory.profile_context(query),
                           'guidance': 'Use related names to resolve relationships, then look up that name. Profile facts are the user\'s own words and win over card values. Missing/ambiguous recipient: ask, never guess.'}, ensure_ascii=False)
    except (OSError, ValueError, subprocess.TimeoutExpired): return 'Contacts unavailable. Use the app address book or ask for the recipient.'


def calendar_backend(data):
    if turn.STOPPING: raise InterruptedError('Request cancelled')
    result = subprocess.run([paths.APP, '--calendar'], input=json.dumps(data), capture_output=True, text=True, timeout=20)
    if result.returncode: raise ValueError('Calendar helper unavailable. Update Rabik and try again.')
    return json.loads(result.stdout)


def calendar_tool(args):
    if args == ['--help'] or not args: return prompts.CALENDAR_HELP
    if not interaction.wait_commit(): return 'Request cancelled.'
    try:
        data = json.loads(' '.join(args))
        if not isinstance(data, dict): raise ValueError('Expected a JSON object.')
        if any(key in data and not isinstance(data[key], str) for key in ('action', 'title', 'from', 'to', 'start', 'end', 'query', 'id', 'calendarID')):
            raise ValueError('Calendar fields must be strings.')
        action = data.get('action')
        if action not in ('list', 'add', 'move', 'delete'): return prompts.CALENDAR_HELP
        if action != 'list' and os.environ.get('RABIK_AGENT_PREP') == '1':
            return 'Call preparation is read-only.'
        def date(value):
            from datetime import datetime
            parsed = datetime.fromisoformat(value)
            if parsed.utcoffset() is None: raise ValueError('Include a timezone offset.')
            return parsed
        if action == 'add':
            if not isinstance(data.get('title'), str) or not data['title'].strip(): raise ValueError('A title is required.')
            if date(data['end']) <= date(data['start']): raise ValueError('End must follow start.')
        else:
            if date(data['to']) <= date(data['from']): raise ValueError('Range end must follow start.')
        if action == 'move':
            date(data['start'])
            if 'end' in data and date(data['end']) <= date(data['start']): raise ValueError('End must follow start.')
        deadline = time.monotonic() + 90   # both cards share one tool's two-minute budget
        result = calendar_backend(data if action in ('list', 'add') else {'action': 'list', 'from': data['from'], 'to': data['to']})
        if result.get('need') == 'calendar': return interaction.need('calendar', 'To read and change your calendar events. Retry the calendar tool after allowing access.')
        if action in ('list', 'add') or 'error' in result: return json.dumps(result, ensure_ascii=False)
        matches = [e for e in result['events'] if (not data.get('id') or e['id'] == data['id']) and
                   (not data.get('query') or data['query'].casefold() in ' '.join([e['title'], *e.get('attendees', [])]).casefold())]
        if not matches: return 'No matching event. Ask for another title or range.'
        def when(d, day=True):   # the offset only when it isn't this Mac's own at that moment
            return d.strftime(('%a %b %-d, ' if day else '') + '%-I:%M %p' + ('' if d.utcoffset() == d.astimezone().utcoffset() else ' %z'))
        def times(start, end):
            s, e = date(start), date(end)
            return when(s) + ' – ' + when(e, e.date() != s.date() or e.utcoffset() != s.utcoffset())
        def label(e): return f"{e['title']} · {times(e['start'], e['end'])} · {e['calendar']}" + (' · ' + ', '.join(e['attendees']) if e.get('attendees') else '') + (' · all day' if e.get('allDay') else '')
        if len(matches) > 1:
            if len(matches) > 8: return 'Too many matches. Ask for a narrower title or range.'
            answer = interaction.ask_user({'pick': 'Which event?', 'options': [label(e) for e in matches]}, max(1, deadline - time.monotonic())) if os.environ.get('RABIK_ASK') else None
            if answer is None or not answer.isdigit() or int(answer) >= len(matches): return 'No event selected. Do not guess.'
            matches = [matches[int(answer)]]
        event = matches[0]
        if not event['writable']: return 'This calendar is read-only. No change made.'
        change = {'action': action, 'event': event}
        if action == 'move':
            start = date(data['start'])
            end = date(data['end']) if 'end' in data else start + (date(event['end']) - date(event['start']))
            change.update(start=start.isoformat(), end=end.isoformat())
        destination = times(change['start'], change['end']) if action == 'move' else 'Deleted'
        if not os.environ.get('RABIK_ASK') or interaction.ask_user({'q': 'Move this event?' if action == 'move' else 'Delete this event?',
                'cmd': f"{event['title']} → {destination} · {'from ' if action == 'move' else ''}{label(event).removeprefix(event['title'] + ' · ')} · this occurrence only"},
                max(1, deadline - time.monotonic())) != 'y': return 'No change made. User approval is required.'
        if turn.STOPPING or not interaction.wait_commit(): return 'Request cancelled.'
        result = calendar_backend(change)
        if result.get('need') == 'calendar': return interaction.need('calendar', 'To change your calendar event. No change made; retry after allowing access.')
        return json.dumps(result, ensure_ascii=False)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        return 'Calendar could not finish: ' + str(error)[:300]
