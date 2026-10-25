"""Feedback from Settings: a prefilled GitHub issue the user previews before anything is sent."""
import os
import platform
import subprocess
import urllib.parse
from brain import paths, prefs, storage, wording

__all__ = ['feedback']


def feedback(data):
    model = prefs.pref('model', 'haiku')
    model = model if model in ('haiku', 'sonnet', 'opus') else 'custom'
    mac = subprocess.run(['/usr/sbin/sysctl', '-n', 'hw.model'], capture_output=True, text=True).stdout.strip()
    text = str(data.get('text', '')).strip()[:4000]   # what the user typed in Settings; they see it in the preview before it goes anywhere
    body = (f'## What happened\n\n{text}\n\n' if text else '## What happened\n\n\n## What you expected\n\n\n') + ('## Rabik\n'
            f'Version: {paths.APP_VERSION}\nVersion / commit: {str(data.get("version", "unknown"))[:80]}\nmacOS: {platform.mac_ver()[0]}\nMac model: {mac}\n'
            f'AI client: {prefs.client()}\nModel: {model}\nRouting: {prefs.routing_mode()}\nSafe mode: {"on" if prefs.pref("safe", True) else "off"}\n'
            f'Input: {"type" if prefs.pref("input", "voice") == "type" else "voice"}\n'
            f'Shortcut: {"toggle" if prefs.pref("talkMode", "hold") == "toggle" else "hold"}\n')
    if data.get('include') is True:
        rows = [r for r in storage.read_rows(os.path.join(paths.DIR, 'log.jsonl')) if r.get('status') != 'not_handled' and isinstance(r.get('task'), str) and wording.plain(r['task']) not in ('report feedback', 'report a bug')]
        body += '\n## My last ask\n' + (rows[-1]['task'] if rows else '(No previous ask)') + '\n'
    return {'body': body, 'include': data.get('include') is True,
            'url': paths.REPOSITORY + '/issues/new?' + urllib.parse.urlencode({'title': 'Rabik feedback', 'body': body})}
