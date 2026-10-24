"""Daily capture stays anonymous and retries failed sends, without network access."""
import json
import os
import platform
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import rabik


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        test_dir = os.environ.pop('RABIK_DIR', None)
        self.addCleanup(lambda: os.environ.__setitem__('RABIK_DIR', test_dir) if test_dir is not None else os.environ.pop('RABIK_DIR', None))

    def test_success_is_daily_and_failure_can_retry(self):
        with tempfile.TemporaryDirectory(prefix='rabik telemetry ') as root:
            root = Path(root)
            curl = root / 'curl'
            curl.write_text('#!/bin/sh\nexit "${FAKE_CURL_STATUS:-0}"\n')
            curl.chmod(0o700)
            spawn = subprocess.Popen

            def fake_send(args, **kwargs):
                payload = json.loads(args[4])
                self.assertEqual(payload['event'], 'used')
                self.assertEqual(payload['api_key'], 'fixture-token')
                self.assertEqual(payload['properties'], {'$process_person_profile': False, 'version': rabik.APP_VERSION,
                                                                  'macos': platform.mac_ver()[0], 'client': 'claude'})
                self.assertEqual(set(payload), {'api_key', 'event', 'distinct_id', 'properties'})
                worker = spawn(args, **kwargs)
                worker.wait(timeout=5)
                return worker

            with patch.object(rabik, 'DIR', str(root)), patch.object(rabik, 'POSTHOG_KEY', 'fixture-token'), \
                 patch.object(rabik, 'pref', return_value=True), patch.object(rabik.subprocess, 'Popen', side_effect=fake_send) as send, \
                 patch.dict(os.environ, {'PATH': str(root), 'FAKE_CURL_STATUS': '22'}):
                rabik.ping()
                self.assertFalse((root / 'pinged').exists())
                identity = (root / 'id').read_text()
                os.environ['FAKE_CURL_STATUS'] = '0'
                rabik.ping()
                self.assertTrue((root / 'pinged').exists())
                rabik.ping()
                self.assertEqual(send.call_count, 2)
                self.assertEqual((root / 'id').read_text(), identity)

    def test_failure_and_used_events_include_the_same_app_version_field(self):
        with tempfile.TemporaryDirectory() as root, patch.object(rabik, 'DIR', root), \
             patch.object(rabik, 'POSTHOG_KEY', 'fixture-token'), \
             patch.object(rabik, 'pref', side_effect=lambda k, d: {'improve': True}.get(k, d)), \
             patch.object(rabik.subprocess, 'Popen') as send:
            rabik.report('Open the fixture', 'Could not open it', (), 1, 'error')
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'task_failed')
        self.assertEqual(payload['properties']['version'], rabik.APP_VERSION)
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'task', 'reply', 'steps', 'why', 'secs', 'model', 'client', 'macos'})

    def test_failure_reports_drop_text_applescript_types_or_writes(self):
        steps = ['osascript -e \'tell application "System Events" to keystroke "hunter2"\'',
                 'osascript -e \'tell application "Notes" to make new note with properties {name:"Diary", body:"private words"}\'',
                 'osascript -e \'tell application "Notes" to set body of note 1 to "private words"\'']
        cleaned = ' '.join(map(rabik.clean, steps))
        self.assertFalse(any(word in cleaned for word in ('hunter2', 'Diary', 'private')))
        self.assertIn('tell application "Notes"', cleaned)

    def test_ask_done_has_counts_and_command_classes_but_no_ask_text(self):
        with tempfile.TemporaryDirectory() as root, patch.object(rabik, 'DIR', root), \
             patch.object(rabik, 'POSTHOG_KEY', 'fixture-token'), patch.object(rabik, 'pref', return_value=True), \
             patch.object(rabik.subprocess, 'Popen') as send:
            rabik.ask_done({'task': 'Private request', 'reply': 'Private answer', 'path': 'shortcut', 'model': 'instant',
                              'secs': 1.26, 'steps': ['one', 'two'], 'ran': [f'{rabik.PLACE} Notes left', f'{rabik.WEB} read secret'],
                              'status': 'completed', 'escalated': False})
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'ask_done')
        self.assertEqual(payload['properties']['tools'], ['place', 'web'])
        self.assertEqual(payload['properties']['status'], 'ok')
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'path', 'model', 'secs', 'steps',
                                                      'tools', 'status', 'escalated', 'macos', 'client'})
        self.assertNotIn('Private', json.dumps(payload))

    def test_ask_done_maps_terminal_states(self):
        with patch.object(rabik, 'posthog') as send:
            for state in ('completed', 'failed', 'cancelled'):
                rabik.ask_done({'status': state})
        self.assertEqual([call.args[1]['status'] for call in send.call_args_list], ['ok', 'failed', 'cancelled'])

    def test_error_shapes_never_include_exception_messages_or_shortcut_words(self):
        with tempfile.TemporaryDirectory() as root, patch.object(rabik, 'DIR', root), \
             patch.object(rabik, 'POSTHOG_KEY', 'fixture-token'), patch.object(rabik, 'pref', return_value=True), \
             patch.object(rabik.subprocess, 'Popen') as send:
            try:
                raise RuntimeError('private crash detail')
            except RuntimeError as error:
                rabik.exception_error(type(error), error.__traceback__)
            rabik.report_error('replay', shortcut='0123456789abcdef', failed_at=2)
        crash, replay = [json.loads(call.args[0][4]) for call in send.call_args_list]
        self.assertEqual(set(crash['properties']), {'$process_person_profile', 'version', 'kind', 'macos', 'client',
                                                    'exception', 'file', 'line', 'function', 'at_line', 'at_function'})
        self.assertEqual(crash['properties']['exception'], 'RuntimeError')
        self.assertNotIn('private crash detail', json.dumps(crash))
        self.assertEqual(replay['properties']['kind'], 'replay')
        self.assertEqual(replay['properties']['shortcut'], '0123456789abcdef')
        self.assertEqual(replay['properties']['failed_at'], 2)

    def test_a_crash_inside_the_standard_library_names_the_rabik_line_and_errno(self):
        code = {}
        exec(compile('import subprocess\ndef go():\n    subprocess.Popen(["/no/such/tool"])\n', rabik.ME, 'exec'), code)   # a frame that counts as rabik.py
        with patch.object(rabik, 'report_error') as sent:
            try:
                code['go']()
            except OSError as error:
                rabik.exception_error(type(error), error.__traceback__, error)
        props = sent.call_args.kwargs
        self.assertEqual((props['at_function'], props['at_line'], props['errno']), ('go', 3, 2))
        self.assertEqual(props['exception'], 'FileNotFoundError')
        self.assertNotEqual(props['file'], 'rabik.py')

    def test_dictation_has_only_mode_counts_timing_and_outcome(self):
        with tempfile.TemporaryDirectory() as root, patch.object(rabik, 'DIR', root), \
             patch.object(rabik, 'POSTHOG_KEY', 'fixture-token'), patch.object(rabik, 'pref', return_value=True), \
             patch.object(rabik.subprocess, 'Popen') as send:
            rabik.dictation_event('cleanup', 1.23456, True, False, False, 'no box')
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'dictation')
        self.assertEqual(payload['properties']['secs'], 1.235)
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'macos', 'client', 'mode', 'secs',
                                                      'cleanup_used', 'fell_back', 'timed_out', 'insert'})

    def test_the_ask_log_and_its_folder_are_private_even_on_older_installs(self):
        with tempfile.TemporaryDirectory() as root, patch.object(rabik, 'DIR', root):
            os.chmod(root, 0o755); log = Path(root, 'log.jsonl'); log.write_text(''); log.chmod(0o644)
            rabik.append_log({'task': 'Summarize my inbox'})
            self.assertEqual((os.stat(root).st_mode & 0o777, log.stat().st_mode & 0o777), (0o700, 0o600))

    def test_disabled_does_not_send(self):
        with tempfile.TemporaryDirectory() as root, patch.object(rabik, 'DIR', root), \
             patch.object(rabik.subprocess, 'Popen') as send:
            with patch.object(rabik, 'POSTHOG_KEY', ''):
                rabik.ping()
            with patch.object(rabik, 'POSTHOG_KEY', 'fixture-token'), \
                 patch.object(rabik, 'pref', side_effect=lambda key, default: True if key == 'improve' else False):
                rabik.ping()
                rabik.ask_done({'status': 'completed'})
                rabik.report_error('stopped')
                rabik.dictation_event('verbatim', 1, False, False, False, 'ok')
                rabik.report('Private request', 'Private reply', (), 1, 'error')
            send.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_new_users_are_counted_by_default(self):
        with tempfile.TemporaryDirectory() as root, patch.object(rabik, 'DIR', root), \
             patch.object(rabik, 'PREFS', str(Path(root) / 'settings.json')), \
             patch.object(rabik, 'POSTHOG_KEY', 'fixture-token'), patch.object(rabik.subprocess, 'Popen') as send:
            rabik.ping()
        send.assert_called_once()


if __name__ == '__main__':
    unittest.main()
