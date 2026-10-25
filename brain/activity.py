"""Activity history (Settings → Memory, off until turned on): the windows, pages and files the user had in front, noted by
Rabik.app (App/Activity.swift) one file a day under activity/. --activity finds "that Figma file yesterday"; the daily recap
lists where the day went."""
import os
import re
from datetime import date, datetime, timedelta
from brain import paths, prefs, sources, storage

__all__ = ['ACTIVITY_DAYS', 'ACTIVITY_STOP', 'activity_rows', 'activity_items', 'activity_search', 'activity_day']


ACTIVITY_DAYS = 30


ACTIVITY_STOP = set('what which where was were is the a an that this those i me my we our you it to of in on at for from with did do '
                    'look looked looking saw see seen open opened read reading had have find show page pages file files doc docs '
                    'document documents site website link links window app tab earlier ago again one thing'.split())


def activity_rows(days=ACTIVITY_DAYS):
    """Every noted window of the last days, oldest first: {start, end, app, bundle, title, url | path}."""
    folder, rows = os.path.join(paths.DIR, 'activity'), []
    first = (date.today() - timedelta(days=days - 1)).isoformat()
    if not os.path.isdir(folder) or os.path.islink(folder): return rows
    for name in sorted(os.listdir(folder)):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.jsonl', name) and name[:10] >= first:
            rows += [r for r in storage.read_rows(os.path.join(folder, name))
                     if isinstance(r.get('title'), str) and isinstance(r.get('start'), (int, float)) and isinstance(r.get('end'), (int, float))]
    return rows


def activity_items(rows):
    """The same page, file or window put together: its total time and when it was last in front, longest first."""
    items = {}
    for r in rows:
        key = r.get('url') or r.get('path') or (r.get('bundle', ''), r['title'])
        item = items.setdefault(str(key), {'title': r['title'], 'app': r.get('app', ''), 'url': r.get('url', ''), 'path': r.get('path', ''),
                                           'seconds': 0, 'last': 0, 'days': set()})
        item['seconds'] += max(0, r['end'] - r['start']); item['days'].add(datetime.fromtimestamp(r['start']).date())
        if r['end'] >= item['last']: item.update(last=r['end'], title=r['title'])
    return sorted(items.values(), key=lambda i: i['seconds'], reverse=True)


def _minutes(seconds):
    return f'{max(1, round(seconds / 60))} min'


def activity_search(words):
    """--activity "<words, weekday or date>": the best 8 matches with their time; the ones an answer uses become source chips."""
    if not prefs.pref('activity', False): return 'Activity history is off. The user can turn it on in Settings → Memory.'
    today, wanted, days = date.today(), [], set()
    for w in re.findall(r'[\w.:/-]+', words.casefold()):
        if w == 'today': days.add(today)
        elif w == 'yesterday': days.add(today - timedelta(days=1))
        elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', w):
            try: days.add(date.fromisoformat(w))
            except ValueError: pass
        elif w in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'):
            back = (today.weekday() - ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday').index(w)) % 7 or 7
            days.add(today - timedelta(days=back))
        elif w not in ACTIVITY_STOP and len(w) > 1: wanted.append(w)
    rows = [r for r in activity_rows() if not days or datetime.fromtimestamp(r['start']).date() in days]
    hay = lambda i: ' '.join([i['title'], i['app'], i['url'], i['path']]).casefold()
    scored = [(sum(w in hay(i) for w in wanted), i) for i in activity_items(rows)]
    hits = [i for score, i in sorted(scored, key=lambda s: (s[0], s[1]['seconds']), reverse=True) if score or not wanted][:8]
    for i in hits[:4]:
        if i['url'] or i['path']: sources.source_note('activity', i['url'] or i['path'], i['title'])
    return '\n'.join(f"{datetime.fromtimestamp(i['last']).strftime('%a %Y-%m-%d %H:%M')} · {i['app']} · {i['title'][:160]} · "
                     f"{i['url'] or i['path'] or 'window'} ({_minutes(i['seconds'])})" for i in hits) or 'Nothing matches in the last 30 days.'


def activity_day(day):
    """The daily recap's "Most time on": the day's three longest pages, files or windows, as short lines."""
    if not prefs.pref('activity', False): return []
    rows = [r for r in activity_rows() if datetime.fromtimestamp(r['start']).date().isoformat() == day]
    return [f"{i['title'][:80]} · {i['app']} · {_minutes(i['seconds'])}" for i in activity_items(rows) if i['seconds'] >= 120][:3]
