"""Universal reading and durable request logs; fake apps and scratch state only."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import tests  # first: scratch RABIK_DIR, no telemetry, host guard
import rabik


class UniversalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.multiple(rabik, DIR=str(self.root), TURN={})
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.env = patch.dict(os.environ, {'RABIK_ASK': str(self.root), 'RABIK_FRONT': 'Unfamiliar Fixture'})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_native_document_paging_retains_full_text_without_repeating_reads(self):
        text = ('An unfamiliar question and its complete answer.\n' * 400) + 'DOCUMENT END'
        worker = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps({'text': text, 'incomplete': False, 'identity': 'window-1'})))
        with patch.object(rabik, 'browser_adapter', return_value=''), patch.object(rabik, 'hands_call', worker), patch.object(rabik, 'window_identity', return_value='window-1'), patch.object(rabik.subprocess, 'run') as ocr:
            pages = [rabik.window_text(offset=n) for n in range(0, len(text), rabik.TEXT_PAGE)]
        self.assertEqual(''.join(p.rsplit('\n[Read ', 1)[0] for p in pages), text)
        self.assertTrue(all(len(p) < 8500 for p in pages))
        worker.assert_called_once(); ocr.assert_not_called()

    def test_native_continuation_finishes_pending_tree_without_losing_text(self):
        chunks = [{'text': 'First question. ' * 1100, 'incomplete': True, 'identity': 'window-1'}, {'text': 'Last question and answer. ' * 500, 'incomplete': False, 'identity': 'window-1'}]
        with patch.object(rabik, 'browser_adapter', return_value=''), patch.object(rabik, 'hands_call', side_effect=[subprocess.CompletedProcess([], 0, json.dumps(c)) for c in chunks]) as worker, \
             patch.object(rabik, 'window_identity', return_value='window-1'):
            first = rabik.window_text()
            middle = rabik.window_text(offset=8000)
            last = rabik.window_text(offset=16000)
            saved = json.loads((self.root / 'window-text.json').read_text())
        self.assertIn('more document text available', first)
        self.assertEqual(saved['text'], chunks[0]['text'] + '\n' + chunks[1]['text'])
        self.assertIn('Last question', last)
        self.assertEqual(worker.call_args_list[1].args[0], ['read', 'Unfamiliar Fixture', 'more'])

    def test_native_continuation_stops_when_no_new_text_arrives(self):
        chunks = [{'text': 'Available text', 'incomplete': True, 'identity': 'window-1'},
                  {'text': '', 'incomplete': True, 'identity': 'window-1'}]
        with patch.object(rabik, 'hands_call', side_effect=[subprocess.CompletedProcess([], 0, json.dumps(c)) for c in chunks]) as worker, \
             patch.object(rabik, 'window_identity', return_value='window-1'):
            rabik.window_text()
            page = rabik.window_text(offset=8000)
        self.assertEqual(worker.call_count, 2)
        self.assertIn('more document text available', page)
        self.assertEqual(json.loads((self.root / 'window-text.json').read_text())['text'], 'Available text')

    def test_native_continuation_is_capped_per_page_request(self):
        chunks = [{'text': 'A', 'incomplete': True, 'identity': 'window-1'}] + [
            {'text': str(i), 'incomplete': True, 'identity': 'window-1'} for i in range(5)]
        with patch.object(rabik, 'hands_call', side_effect=[subprocess.CompletedProcess([], 0, json.dumps(c)) for c in chunks]) as worker, \
             patch.object(rabik, 'window_identity', return_value='window-1'):
            rabik.window_text()
            page = rabik.window_text(offset=8000)
        self.assertEqual(worker.call_count, 5)
        self.assertIn('more document text available', page)

    def test_short_real_ax_text_is_not_replaced_by_ocr(self):
        with patch.object(rabik, 'browser_adapter', return_value=''), patch.object(rabik, 'hands_call', return_value=subprocess.CompletedProcess([], 0, '{"text":"Toolbar"}')), \
             patch.object(rabik.subprocess, 'run') as worker:
            result = rabik.window_text()
        self.assertIn('Toolbar', result)
        worker.assert_not_called()

    def test_web_area_found_by_full_read_uses_dom_without_a_keydown_hint(self):
        with patch.object(rabik, 'hands_call', return_value=subprocess.CompletedProcess([], 0, '{"text":"Page chrome","web":true}')), \
             patch.object(rabik, 'web', return_value='Controls:\n1 box: Answer 1\n\nPage text:\nQ1') as web:
            result = rabik.window_text()
        self.assertTrue(result.startswith('Controls:'))
        web.assert_called_once()

    def test_empty_ax_uses_existing_ocr_under_the_same_reader(self):
        with patch.object(rabik, 'browser_adapter', return_value=''), patch.object(rabik, 'hands_call', return_value=subprocess.CompletedProcess([], 0, '{"text":"","identity":"window-1"}')), \
             patch.object(rabik.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Visible question from unfamiliar app.')) as worker:
            result = rabik.window_text()
        self.assertIn('OCR (visible window text only)', result)
        self.assertEqual(worker.call_args.args[0], [rabik.APP, '--text', 'Unfamiliar Fixture', ''])

    def test_browser_reader_pins_target_and_passes_offsets(self):
        (self.root / 'window-summary.json').write_text(json.dumps({'app': 'Safari', 'web': True, 'incomplete': True}))
        with patch.object(rabik, 'web', return_value='Question ' * 900 + '\n[Read 0-8000 of 12000 chars; 4000 more chars]') as web:
            rabik.window_text('Safari')
            rabik.window_text('Safari', 8000)
        self.assertEqual(web.call_args_list[0].kwargs, {'app': 'Safari', 'fresh': True})
        self.assertEqual(web.call_args_list[1].args, ('read', '8000'))

    def test_browser_probe_requires_a_web_area_in_the_ax_head(self):
        (self.root / 'window-summary.json').write_text(json.dumps({'app': 'Unfamiliar Fixture', 'web': False, 'incomplete': True}))
        state = subprocess.CompletedProcess([], 0, '{"text":"Native document","identity":"window-1"}')
        with patch.object(rabik, 'web') as web, patch.object(rabik, 'hands_call', return_value=state):
            self.assertIn('Native document', rabik.window_text())
        web.assert_not_called()

    def test_keydown_summary_is_bounded_and_uses_the_fast_native_head(self):
        state = {'app': 'Fixture', 'window': 'Document', 'page': 'https://fixture.invalid', 'web': True,
                 'identity': 'window-1', 'text': 'private document words ' * 500}
        with patch.object(rabik, 'hands_call', return_value=subprocess.CompletedProcess([], 0, json.dumps(state))) as worker:
            summary = rabik.window_summary('Fixture')
        self.assertLessEqual(len(summary['text']), 1500)
        self.assertEqual(worker.call_args.args[0], ['read', 'Fixture'])
        self.assertEqual(worker.call_args.kwargs, {'timeout': .4, 'head': True})

    def test_cached_native_page_rejects_a_different_window(self):
        state = {'text': 'first window', 'incomplete': False, 'identity': 'window-1'}
        with patch.object(rabik, 'browser_adapter', return_value=''), patch.object(rabik, 'hands_call', return_value=subprocess.CompletedProcess([], 0, json.dumps(state))), \
             patch.object(rabik, 'window_identity', return_value='window-2'):
            rabik.window_text()
            self.assertIn('window changed', rabik.window_text(offset=1).lower())

    def test_screens_empty_or_invalid_output_is_unavailable(self):
        for output in ('', 'not json', 'null', '[null]', '[["Display",null,0,100,100,true]]'):
            with patch.object(rabik.subprocess, 'run', return_value=Mock(stdout=output)):
                self.assertEqual(rabik.screens(), [])
        self.assertIn('unavailable', rabik.describe([]))

    def test_cancelled_ask_and_active_step_have_durable_timings(self):
        rabik.begin_turn('Fill an unfamiliar worksheet')
        rabik.TURN['step_times'].append({'label': 'Reading', '_start': rabik.time.monotonic() - 2, 'status': 'running'})
        rabik.checkpoint(steps=['Reading'])
        rabik.end_turn()
        rows = rabik.read_rows(str(self.root / 'log.jsonl'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'cancelled')
        self.assertEqual(rows[0]['task'], 'Fill an unfamiliar worksheet')
        self.assertGreaterEqual(rows[0]['step_times'][0]['secs'], 2)
        snapshots = [json.loads(line) for line in (self.root / 'log.jsonl').read_text().splitlines()]
        self.assertIn('task', snapshots[0])
        self.assertTrue(all(not any(k in row for k in ('task', 'reply', 'steps', 'ran')) for row in snapshots[1:]))

    def test_completed_tool_durations_and_failed_request_preserve_steps(self):
        rabik.begin_turn('Read and act')
        p = Mock(); p.ask = ''; p.stdin = io.StringIO(); p.errors = io.StringIO(); p.returncode = 0
        p.stdout = map(json.dumps, [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't', 'name': 'Bash', 'input': {'command': 'fixture read'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't', 'is_error': True}]}},
            {'type': 'result', 'result': 'Failed.', 'is_error': True}])
        with patch.object(rabik, 'say'):
            rabik.run('Read and act', p)
        rabik.end_turn('crashed')
        row = rabik.read_rows(str(self.root / 'log.jsonl'))[0]
        self.assertNotIn('ran', row)
        self.assertEqual(row['step_times'][0]['label'], 'Working on it')
        self.assertEqual(row['step_times'][0]['status'], 'failed')
        self.assertGreaterEqual(row['step_times'][0]['secs'], 0)
        self.assertEqual(row['status'], 'crashed')

    def test_timeout_is_logged_and_cancels_the_owned_worker(self):
        rabik.begin_turn('Slow unfamiliar task')
        p = Mock(); p.ask = ''; p.stdin = io.StringIO(); p.returncode = 0
        timer = Mock()
        with patch.object(rabik.threading, 'Timer', return_value=timer) as factory, patch.object(rabik, 'stop_claude') as stop:
            def stream():
                factory.call_args.args[1](*factory.call_args.kwargs['args'])
                yield from ()
            p.stdout = stream()
            rabik.run('Slow unfamiliar task', p)
        stop.assert_called_once_with(p)
        timer.cancel.assert_called()
        self.assertFalse(rabik.run.ok)
        self.assertEqual(rabik.read_rows(str(self.root / 'log.jsonl'))[0]['status'], 'timed_out')

    def test_successful_retry_is_not_failed_by_the_previous_timeout(self):
        rabik.begin_turn('Slow unfamiliar task')
        rabik.end_turn('timed_out')
        p = Mock(); p.ask = ''; p.stdin = io.StringIO(); p.returncode = 0
        p.stdout = [json.dumps({'type': 'result', 'result': 'Done.', 'is_error': False})]
        with patch.object(rabik, 'say'):
            rabik.run('Retry slow unfamiliar task', p)
        self.assertTrue(rabik.run.ok)

    def test_idle_deadline_resets_on_tool_progress(self):
        rabik.begin_turn('Task with progress')
        p = Mock(); p.ask = ''; p.stdin = io.StringIO(); p.returncode = 0
        p.stdout = map(json.dumps, [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't', 'name': 'Bash', 'input': {'command': 'fixture read'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't', 'content': 'Observed fixture state'}]}},
            {'type': 'result', 'result': 'Done.', 'is_error': False}])
        timer = Mock()
        with patch.object(rabik.threading, 'Timer', return_value=timer) as factory, patch.object(rabik, 'say'):
            rabik.run('Task with progress', p)
        self.assertEqual(factory.call_count, 3)
        self.assertGreaterEqual(timer.cancel.call_count, 3)
        self.assertTrue(rabik.run.ok)

    def test_idle_deadline_pauses_while_a_card_waits(self):
        rabik.begin_turn('Wait for approval')
        p = Mock(); p.ask = ''; p.stdin = io.StringIO(); p.returncode = 0
        timer = Mock()
        with patch.object(rabik.threading, 'Timer', return_value=timer) as factory, \
             patch.object(rabik, 'stop_claude') as stop:
            def stream():
                p.waiting.set()
                factory.call_args.args[1](*factory.call_args.kwargs['args'])
                p.waiting.clear()
                yield json.dumps({'type': 'result', 'result': 'Done.', 'is_error': False})
            p.stdout = stream()
            rabik.run('Wait for approval', p)
        stop.assert_not_called()
        self.assertEqual(factory.call_count, 2)
        self.assertTrue(rabik.run.ok)

    def test_presenting_an_allow_card_resets_the_idle_deadline(self):
        card = Path(rabik.question_path(self.root)); card.parent.mkdir(parents=True, exist_ok=True)
        card.write_text(json.dumps({'q': 'Allow?', 'cmd': 'Fixture action'}))
        p = Mock(); p.poll.side_effect = [None, 0]; p.progress = Mock()
        with patch.object(rabik, 'osa', return_value="Don't Allow"), patch.object(rabik.time, 'sleep'):
            rabik.relay(p, str(self.root))
        p.progress.assert_called_once()

    def test_sigterm_keeps_cancelled_request_in_scratch_log(self):
        import sys
        import time
        ready = self.root / 'ready'
        script = "import os,signal,time,rabik; from pathlib import Path; os.setpgrp(); rabik.begin_turn('Cancelled worksheet'); signal.signal(signal.SIGTERM,rabik.stop_workers); Path(" + repr(str(ready)) + ").touch(); time.sleep(30)"
        worker = subprocess.Popen([sys.executable, '-c', script], cwd=Path(rabik.ME).parent,
                                  env={**os.environ, 'RABIK_DIR': str(self.root)})
        self.addCleanup(lambda: worker.kill() if worker.poll() is None else None)
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline: time.sleep(.01)
        self.assertTrue(ready.exists())
        worker.terminate(); worker.wait(timeout=3)
        self.assertEqual(rabik.read_rows(str(self.root / 'log.jsonl'))[0]['status'], 'cancelled')

    def test_dead_owner_has_interrupted_ask_instead_of_disappearing(self):
        rabik.begin_turn('Pending ask')
        with patch.object(rabik.os, 'getpid', return_value=-1), patch.object(rabik.os, 'kill', side_effect=ProcessLookupError):
            row = rabik.read_rows(str(self.root / 'log.jsonl'))[0]
        self.assertEqual(row['status'], 'interrupted')

    def test_generic_and_site_searches_keep_the_fast_path(self):
        with patch.object(rabik, 'skills', return_value={}), patch.object(rabik, 'show', return_value='opened search') as show:
            self.assertEqual(rabik.fast('search for unfamiliar words'), 'Searched unfamiliar words.')
            self.assertIn('google.com/search?q=unfamiliar%20words', show.call_args.args[0])
            self.assertEqual(rabik.fast('search youtube for unfamiliar words'), 'Searched unfamiliar words on youtube.')
            self.assertEqual(show.call_args.args[0], 'https://duckduckgo.com/?q=!youtube+unfamiliar+words')
            self.assertEqual(rabik.fast('search for restaurants in boston'), 'Searched restaurants in boston.')
            self.assertIn('restaurants%20in%20boston', show.call_args.args[0])
            self.assertEqual(rabik.fast('search for reporting on unfamiliar events'), 'Searched reporting on unfamiliar events.')

    def test_failed_fast_launches_fall_through_without_recording_success(self):
        failed = subprocess.CompletedProcess([], 1)
        with patch.object(rabik, 'skills', return_value={}), patch.object(rabik, 'fast_hands', return_value=None), \
             patch.object(rabik, 'show', return_value='could not open search'):
            self.assertIsNone(rabik.fast('search for unfamiliar words'))
            self.assertEqual(rabik.fast.cmds, [])
        with patch.object(rabik, 'skills', return_value={}), patch.object(rabik, 'fast_hands', return_value=None), \
             patch.object(rabik.subprocess, 'run', return_value=failed):
            self.assertIsNone(rabik.fast('open unfamiliar.example'))
            self.assertEqual(rabik.fast.cmds, [])
        with patch.object(rabik, 'skills', return_value={}), patch.object(rabik, 'fast_hands', return_value=None), \
             patch.object(rabik, 'app_named', return_value='Fixture'), patch.object(rabik.subprocess, 'run', return_value=failed):
            self.assertIsNone(rabik.fast('open fixture'))
            self.assertEqual(rabik.fast.cmds, [])

    def test_polite_opens_take_the_fast_path_but_bare_words_and_tasks_do_not(self):
        ok = subprocess.CompletedProcess([], 0)
        (self.root / 'Downloads').mkdir()
        with patch.object(rabik, 'skills', return_value={}), patch.object(rabik, 'fast_hands', return_value=None), patch.object(rabik, 'free_focus'), \
             patch.object(rabik, 'HOME', str(self.root)), patch.object(rabik, 'app_named', side_effect=lambda name: 'Fixture' if name == 'fixture' else None), \
             patch.object(rabik, 'LAST', str(self.root / 'last_app')), patch.object(rabik.subprocess, 'run', return_value=ok) as run, patch.object(rabik, 'show') as show:
            self.assertEqual(rabik.fast('Can you open up unfamiliar.com?'), 'Opened unfamiliar.com.')
            self.assertEqual(run.call_args.args[0], ['open', 'https://unfamiliar.com'])
            self.assertEqual(rabik.fast('Um, could you please open up Fixture for me?'), 'Opened Fixture.')
            self.assertEqual(run.call_args.args[0], ['open', '-a', 'Fixture'])
            run.reset_mock()
            for ask in ('open homework', 'open unfamiliar', 'Can you open up Unfamiliar?', 'Um, search Unfamiliar for e-bikes and find me the cheapest one.',
                        'What am I looking at?', 'open downloads', 'open it', 'Can you open up?', 'open my unfamiliar homework', 'open unfamiliar and play music'):
                self.assertIsNone(rabik.fast(ask), ask)   # one bare word may be his file or tab, not <word>.com: the AI finds it
        run.assert_not_called(); show.assert_not_called()

    def test_video_promises_stay_on_the_same_instant_path(self):
        apps = {'chrome': 'Google Chrome', 'terminal': 'Terminal', 'notes': 'Notes', 'safari': 'Safari'}
        app_named = lambda words: apps.get(words.lower().strip(' .!?'))
        saved = {'work mode': {'cmds': [f'{rabik.PLACE} Safari full current'], 'reply': 'Work mode ready.', 'at': '2026-10-01'}}
        ok = subprocess.CompletedProcess([], 0)
        with patch.multiple(rabik, app_named=app_named, proc_of=lambda app: app, request_screen=lambda: 'current',
                            place=lambda app, where='full', screen='current', title='': f'{app} window -> {where}',
                            show=lambda target, bg=False: f'opened {target}', skills=lambda: saved, save_skills=lambda _: None,
                            fast_hands=lambda _: None, free_focus=lambda **_: None, LAST=str(self.root / 'last_app')), \
             patch.object(rabik.subprocess, 'run', return_value=ok):
            expected = {
                'Chrome left, Terminal right': 'Google Chrome: left; Terminal: right.',
                'work mode': 'Work mode ready.',
                'full screen Chrome': 'Google Chrome: full screen.',
                'put Notes on the right': 'Notes: right.',
                'open Safari': 'Opened Safari.',
            }
            for said, reply in expected.items():
                with self.subTest(said=said):
                    self.assertEqual(rabik.fast(said), reply)

    def test_agent_titles_start_at_the_words_that_matter(self):
        self.assertEqual(rabik.agent_title('Can you do the steps and get me the post hog API key?'), 'Get post hog API key')
        self.assertEqual(rabik.agent_title('Hey Rabik, um, can you start a Zoom meeting?'), 'Start Zoom meeting')
        self.assertEqual(rabik.agent_title('Can you?'), 'Background task')

    def test_searching_an_installed_app_defers_to_the_ai(self):
        with patch.object(rabik, 'skills', return_value={}), patch.object(rabik, 'app_named', side_effect=lambda name: 'Fixture' if name == 'fixture' else None), \
             patch.object(rabik, 'show') as show:
            self.assertIsNone(rabik.fast('search fixture for unfamiliar words'))
        show.assert_not_called()

    def test_app_names_derive_from_installed_apps_and_ambiguous_names_defer(self):
        empty = Mock(returncode=0); empty.communicate.return_value = ('', '')
        with patch.object(rabik, '_APPS_CACHE', (0, set())), patch.object(rabik.os.path, 'isdir', return_value=True), \
             patch.object(rabik.os, 'listdir', return_value=['Fixture Alpha Editor.app', 'Unfamiliar Editor.app']), \
             patch.object(rabik.subprocess, 'Popen', return_value=empty):
            self.assertEqual(rabik.app_named('fa editor'), 'Fixture Alpha Editor')
            self.assertEqual(rabik.app_named('fixturealphaeditor'), 'Fixture Alpha Editor')
            self.assertIsNone(rabik.app_named('editor'))
            self.assertIsNone(rabik.app_named('editor history'))
        with patch.object(rabik, '_APPS_CACHE', (0, set())), patch.object(rabik.os.path, 'isdir', return_value=True), \
             patch.object(rabik.os, 'listdir', side_effect=lambda d: ['Finder.app'] if d == '/System/Library/CoreServices' else []), \
             patch.object(rabik.subprocess, 'Popen', return_value=empty):
            self.assertEqual(rabik.app_named('finder'), 'Finder')

    def test_app_discovery_uses_fast_cached_spotlight_results_with_folder_fallback(self):
        found = Mock(returncode=0)
        found.communicate.return_value = ('/Applications/Bundle/Pages.app\n/System/Applications/Notes.app\n', '')
        with patch.object(rabik, '_APPS_CACHE', (0, set())), patch.object(rabik.os.path, 'isdir', return_value=True), \
             patch.object(rabik.os, 'listdir', return_value=['Fallback.app']), \
             patch.object(rabik.subprocess, 'Popen', return_value=found) as run:
            self.assertEqual(rabik.app_named('Pages'), 'Pages')
            self.assertIn('Fallback', rabik.installed_apps())
            self.assertEqual(run.call_count, 1)
            found.communicate.assert_called_once_with(timeout=.08)

    def test_general_method_and_prompt_budget(self):
        self.assertIn('read text →', rabik.SYSTEM)
        self.assertIn('the Allow card confirms—never ask in the reply', rabik.SYSTEM)
        self.assertNotIn('pages needed to reach the controls index', rabik.SYSTEM)
        self.assertIn('do not search for another copy', rabik.SYSTEM)
        self.assertNotIn('on Amazon', rabik.SYSTEM)
        full = rabik.SYSTEM + rabik.ASK_ME + rabik.POINTER + rabik.LEARN_ME + rabik.TEACH + rabik.ASK_FIRST + rabik.WORKFLOW
        self.assertLessEqual(tests.prompt_chars(full), 10000)
        print(f'UNIVERSAL PROMPT CHARS (installed): {tests.prompt_chars(full)}; TEXT PAGE CHARS: {rabik.TEXT_PAGE}', flush=True)
