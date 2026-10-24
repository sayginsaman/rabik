"""Local meeting journal, recovery, privacy and dashboard commands."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import atticus


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        p = patch.object(atticus, 'DIR', str(self.root)); p.start(); self.addCleanup(p.stop)
        self.folder = self.root / 'meetings' / 'fake-call'
        self.folder.mkdir(parents=True, mode=0o700)
        meta = self.folder / 'metadata.json'
        meta.write_text(json.dumps({'started': 1791745200, 'title': 'Cedar budget', 'app': 'Zoom'})); meta.chmod(0o600)
        events = self.folder / 'events.jsonl'; events.touch(mode=0o600)

    def test_incremental_stream_survives_kill_and_torn_tail(self):
        script = "import atticus,time; atticus.meeting_append('fake-call', {'kind':'transcript','text':'Launch Friday','speaker':'You','seconds':12}); time.sleep(30)"
        p = subprocess.Popen([sys.executable, '-c', script], cwd=Path(atticus.ME).parent, env={**os.environ, 'ATTICUS_DIR': str(self.root)})
        self.addCleanup(lambda: p.poll() is None and p.kill())
        import time
        deadline = time.monotonic() + 15
        events = self.folder / 'events.jsonl'
        while not events.stat().st_size and time.monotonic() < deadline: time.sleep(.01)
        p.kill(); p.wait(timeout=3)
        with events.open('a') as f: f.write('{"kind":"trans')
        m = atticus.meeting_read('fake-call')
        self.assertEqual(m['transcript'][0]['text'], 'Launch Friday')
        self.assertEqual(m['duration'], 12)
        self.assertEqual(m['status'], 'Interrupted or listening')
        for f in self.folder.iterdir(): self.assertEqual(f.stat().st_mode & 0o777, 0o600)

    def test_search_date_export_delete_and_boundaries(self):
        atticus.meeting_append('fake-call', {'kind': 'transcript', 'text': 'We will follow up on pricing.', 'speaker': 'You', 'seconds': 62})
        atticus.meeting_append('fake-call', {'kind': 'ended', 'at': 1791745262, 'duration': 62})
        self.assertEqual(len(atticus.meeting_list('PRICING cedar')), 1)
        date = atticus.datetime.fromtimestamp(1791745200).strftime('%Y-%m-%d')
        self.assertIn('pricing', atticus.meeting_history(date))
        self.assertIn('pricing', atticus.meeting_history(atticus.datetime.fromtimestamp(1791745200).strftime('%A')))
        self.assertIn('pricing', atticus.meeting_history("What did we decide in " + atticus.datetime.fromtimestamp(1791745200).strftime('%A') + "'s meeting?"))
        with patch.object(atticus.shutil, 'which', return_value=None):
            m = atticus.meeting_finish('fake-call')
        self.assertEqual(m['action_items'], ['We will follow up on pricing.'])
        md = atticus.meeting_command({'action': 'export', 'id': 'fake-call'})['markdown']
        self.assertIn('[00:01:02] You: We will', md)
        for bad in ['../settings', '', None, '/tmp', 'fake-call/metadata.json']:
            with self.assertRaises(ValueError): atticus.meeting_path(bad)
        link = self.root / 'meetings' / 'alias'; link.symlink_to(self.folder)
        with self.assertRaises(ValueError): atticus.meeting_path('alias')
        result = atticus.meeting_command({'action': 'delete', 'id': 'fake-call'})
        self.assertEqual(result['deleted'], 'fake-call'); self.assertFalse(self.folder.exists())

    def test_summary_reads_the_transcript_once_only_when_switched_on(self):
        atticus.meeting_append('fake-call', {'kind': 'transcript', 'text': 'We agreed on the budget', 'seconds': 10})
        quiet = self.root / 'meetings' / 'quiet-call'; quiet.mkdir(mode=0o700)
        (quiet / 'metadata.json').write_text(json.dumps({'started': 1791745200, 'title': 'Quiet', 'app': 'Zoom'})); (quiet / 'events.jsonl').touch(mode=0o600)
        atticus.meeting_append('quiet-call', {'kind': 'transcript', 'text': 'PRIVATE WORDS', 'seconds': 10})
        with patch.object(atticus.shutil, 'which', return_value='/fake/claude'), patch.object(atticus, 'meeting_call', return_value=('{"summary":"Budget agreed","action_items":[]}', {})) as call:
            atticus.meeting_finish('fake-call'); atticus.meeting_finish('fake-call')
            call.assert_called_once()
            self.assertIn('Them: We agreed on the budget', str(call.call_args))
            self.assertEqual(atticus.meeting_read('fake-call')['summary'], 'Budget agreed')
            call.reset_mock()
            with patch.object(atticus, 'pref', side_effect=lambda k, d=None: False if k == 'meetingSummary' else d):
                result = atticus.meeting_finish('quiet-call')
            call.assert_not_called()   # off: nothing leaves the Mac, the local recap stays
            self.assertIn('PRIVATE WORDS', result['summary'])

    def test_failed_summary_keeps_transcript_and_local_recap(self):
        atticus.meeting_append('fake-call', {'kind': 'transcript', 'text': 'Opening words', 'seconds': 0})
        atticus.meeting_append('fake-call', {'kind': 'notes', 'text': 'Notes'})
        atticus.meeting_append('fake-call', {'kind': 'answer', 'lines': ['Answer']})
        with patch.object(atticus.shutil, 'which', return_value='/fake/claude'), patch.object(atticus, 'meeting_call', side_effect=RuntimeError('offline')):
            result = atticus.meeting_finish('fake-call')
        self.assertIn('Opening words', result['summary'])
        self.assertEqual(len(result['transcript']), 1)

    def test_private_files_cannot_redirect_history(self):
        for name in ['metadata.json', 'events.jsonl']:
            original = (self.folder / name).read_text()
            (self.root / 'secret').write_text(original)
            (self.folder / name).unlink(); (self.folder / name).symlink_to(self.root / 'secret')
            with self.assertRaises(OSError): atticus.meeting_read('fake-call')
            self.assertEqual(atticus.meeting_list(), [])
            (self.folder / name).unlink(); (self.folder / name).write_text(original)

    def test_partial_recovery_and_finalization_do_not_duplicate(self):
        atticus.meeting_append('fake-call', {'kind': 'partial', 'you': 'I will follow up', 'them': 'Launch Fri', 'seconds': 2})
        self.assertEqual(len(atticus.meeting_read('fake-call')['transcript']), 2)
        atticus.meeting_append('fake-call', {'kind': 'transcript', 'mic': False, 'speaker': 'Zoom', 'text': 'Launch Friday.', 'seconds': 3})
        m = atticus.meeting_read('fake-call')
        self.assertEqual([r['text'] for r in m['transcript']], ['Launch Friday.', 'I will follow up'])
        self.assertTrue(m['transcript'][-1]['recovered'])

    def test_resume_discards_in_flight_recap_and_finishes_full_transcript(self):
        atticus.meeting_append('fake-call', {'kind':'transcript','text':'Opening decision','seconds':10})
        atticus.meeting_append('fake-call', {'kind':'ended','at':1,'duration':10})
        def resume(system, said):
            atticus.meeting_append('fake-call', {'kind':'resumed','duration':10})
            atticus.meeting_append('fake-call', {'kind':'transcript','text':'Resumed decision','seconds':20})
            return '{"summary":"STALE RECAP","action_items":[]}', {}
        with patch.object(atticus.shutil,'which',return_value='/fake/claude'),patch.object(atticus,'meeting_call',side_effect=resume):
            result=atticus.meeting_finish('fake-call')
        self.assertNotIn('STALE RECAP',(self.folder/'events.jsonl').read_text())
        self.assertEqual(result['summary'],'')
        atticus.meeting_append('fake-call', {'kind':'ended','at':2,'duration':20})
        with patch.object(atticus.shutil,'which',return_value='/fake/claude'),patch.object(atticus,'meeting_call',return_value=('{"summary":"Full recap","action_items":[]}',{})) as call:
            result=atticus.meeting_finish('fake-call');atticus.meeting_finish('fake-call')
        self.assertEqual(result['summary'],'Full recap');call.assert_called_once()
        self.assertIn('Resumed decision',call.call_args.args[1])
        self.assertEqual(len(result['transcript']),2)

    def test_cancelled_summary_lock_does_not_block_the_next_finish(self):
        (self.folder/'summary.once').touch(mode=0o600)
        atticus.meeting_append('fake-call',{'kind':'transcript','text':'Survives cancellation','seconds':10})
        with patch.object(atticus.shutil,'which',return_value=None):
            result=atticus.meeting_finish('fake-call')
        self.assertIn('Survives cancellation',result['summary'])
