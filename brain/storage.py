"""Private JSON files written whole, and JSON-lines logs read back tolerant of a torn last line."""
import json
import os
import tempfile
import time
from brain import paths

__all__ = ['private_json', 'read_rows', 'append_log']


def append_log(row):
    os.makedirs(paths.DIR, mode=0o700, exist_ok=True); os.chmod(paths.DIR, 0o700)   # older installs made it (and memory.md) readable to other Mac accounts
    fd = os.open(os.path.join(paths.DIR, 'log.jsonl'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try: os.fchmod(fd, 0o600); os.write(fd, (json.dumps(row) + '\n').encode())
    finally: os.close(fd)


def private_json(path, data):
    with tempfile.NamedTemporaryFile(mode='w', dir=os.path.dirname(path), delete=False) as f:
        os.fchmod(f.fileno(), 0o600); json.dump(data, f, ensure_ascii=False); tmp = f.name
    try: os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def read_rows(path):
    try:
        with open(path) as f:
            rows = []
            for line in f:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except ValueError:
                    continue   # a cancelled write must not hide the rest of the history
            folded, positions = [], {}
            for row in rows:
                id_ = row.get('id') if isinstance(row.get('id'), str) else None
                if id_ and id_ in positions: folded[positions[id_]].update(row)
                else:
                    if id_: positions[id_] = len(folded)
                    folded.append(row)
            for row in folded:
                if row.get('status') == 'running' and row.get('pid') != os.getpid():
                    try: age = time.time_ns() - int(row.get('id', '0-0').rsplit('-', 1)[-1])
                    except ValueError: age = 0
                    if age > 600 * 1_000_000_000:
                        row['status'] = 'interrupted'
                        continue
                    try: os.kill(row['pid'], 0)
                    except ProcessLookupError: row['status'] = 'interrupted'
                    except (OSError, KeyError, TypeError): pass
            return folded
    except OSError:
        return []
