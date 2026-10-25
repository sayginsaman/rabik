"""What an answer read from Rabik's own records: helper commands note each meeting, fact, page or person they returned
in the ask's folder, and the answer shows them as chips. Only records really read become chips; the model can't add one."""
import json
import os
from brain import environ, storage

__all__ = ['SOURCE_KINDS', 'source_note', 'source_report']


SOURCE_KINDS = ('meeting', 'day', 'activity', 'person', 'fact')


def source_note(kind, ident, label, **extra):
    """Called by --meeting-history, --me find, --activity, --people inside an ask (RABIK_ASK); a no-op anywhere else."""
    ask = environ.ask_dir()
    if kind not in SOURCE_KINDS or not ask or not os.path.isdir(ask): return
    row = {'kind': kind, 'id': str(ident)[:2000], 'label': ' '.join(str(label).split())[:80], **extra}
    try:
        with open(os.path.join(ask, 'sources.jsonl'), 'a') as f: f.write(json.dumps(row, ensure_ascii=False) + '\n')
    except OSError: pass


def source_report(directory=None):
    """At the end of an ask: up to 4 distinct sources, first read first, as one ⌖ line under the answer."""
    ask = directory or environ.ask_dir()
    if not ask: return []
    path, seen, picked = os.path.join(ask, 'sources.jsonl'), set(), []
    for row in storage.read_rows(path):
        key = (row.get('kind'), row.get('id'))
        if row.get('kind') in SOURCE_KINDS and row.get('id') and key not in seen:
            seen.add(key); picked.append(row)
    try: os.remove(path)
    except OSError: pass
    picked = picked[:4]
    if picked and environ.in_box(): print('⌖ ' + json.dumps(picked, ensure_ascii=False), flush=True)
    return picked
