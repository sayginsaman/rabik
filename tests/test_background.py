"""Background tasks use fake workers; no user apps, windows, or configuration."""
import shlex
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import atexit
import shutil
import signal
import time
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.agents, brain.apps, brain.cli, brain.clients, brain.handoffs, brain.hands, brain.instant, brain.interaction
import brain.macos, brain.paths, brain.policy, brain.prefs, brain.prompts, brain.protocol, brain.screen, brain.skills
import brain.turn, brain.web, brain.windows
from tests import native_source, scratch_dir


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        root = scratch_dir(self)
        for p in [patch.dict(os.environ, {'RABIK_ASK': str(root)}, clear=True),
                  patch.object(brain.paths, 'WORKED', str(root / 'worked.json')),
                  patch.object(brain.interaction, 'wait_commit', return_value=True)]:
            p.start(); self.addCleanup(p.stop)
        self.target = {'pid': 123, 'windowID': '42', 'windowFrame': [0, 0, 300, 200], 'app': 'Notes', 'window': 'Fixture'}

    def gate(self, cmd):
        with patch('sys.stdin', io.StringIO(json.dumps({'tool_input': {'command': cmd}}))), patch('sys.stdout', new_callable=io.StringIO) as out, patch.object(brain.macos, 'preview_app'):
            brain.policy.gate()
        return json.loads(out.getvalue())['hookSpecificOutput']['permissionDecision'] if out.getvalue() else 'allow'

    def test_instant_open_tells_the_focus_guard_it_was_asked(self):
        calls = []
        run = lambda cmd, **_: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, '', '')
        with patch.object(brain.paths, 'LAST', os.path.join(os.environ['RABIK_ASK'], 'last')), \
             patch.object(brain.apps, 'app_named', return_value='Fixture'), patch.object(brain.skills, 'skills', return_value={}), \
             patch.object(brain.prefs, 'pref', side_effect=lambda k, v=None: v), patch.object(subprocess, 'run', side_effect=run):
            for words in ('launch fixture', 'open fixture'):
                calls.clear()
                with self.subTest(words=words):
                    self.assertEqual(brain.instant.fast(words).reply, 'Opened Fixture.')
                    self.assertEqual(calls[-1], ['open', '-a', 'Fixture'])
                    self.assertEqual(calls[:-1], [[brain.paths.APP, '--raise', 'user']] if words.startswith('launch') else [])   # "open" was freed by allow_focus already
            calls.clear()
            with patch.object(brain.windows, 'move_target', return_value=('Fixture', 'left', 'current')), \
                 patch.object(brain.windows, 'place', return_value='Fixture window -> left of Main'):
                self.assertEqual(brain.instant.fast('launch fixture on the left').reply, 'Fixture: left.')
            self.assertEqual(calls[:2], [[brain.paths.APP, '--raise', 'user'], ['open', '-a', 'Fixture']])   # the inner "open" must not hide that the user asked

    def test_settings_and_tool_hints_never_steer_to_focus(self):
        self.assertIn('System settings: shell, defaults or AppleScript first; else open the pane with --bg', brain.prompts.system_prompt(brain.prompts.ASK_FIRST))
        self.assertTrue(brain.hands.hands_valid(['click', 'Night Shift…', 'front']) and brain.hands.hands_valid(['click', 'Done', 'near', 'Sheet', 'double', 'front']))
        self.assertFalse(brain.hands.hands_valid(['click', 'Done', 'front', 'front']))
        swift = native_source()
        # --front grants focus for the rest of the ask; a tool reply suggesting it made System Settings stay in front for "is Night Shift on?"
        self.assertNotIn('--front', swift); self.assertNotIn('Bring the window forward', swift)
        self.assertIn('case "front": guard !front', swift)

    def test_recursive_ask_and_unrequested_activation_are_denied(self):
        self.assertEqual(self.gate(f'env -u RABIK_ASK -u CLAUDECODE python3 {shlex.quote(brain.paths.ME)} ask again'), 'deny')
        self.assertEqual(self.gate(f'python3 {shlex.quote(brain.paths.ME)} --wait'), 'deny')
        self.assertEqual(self.gate(f'env -u RABIK_ASK {shlex.quote(brain.paths.ME)} ask again'), 'deny')
        self.assertEqual(self.gate(f'cd {shlex.quote(os.path.dirname(brain.paths.ME))} && env -u RABIK_ASK sh rabik.py ask again'), 'deny')   # the sh header makes sh a launcher
        self.assertEqual(self.gate(f'xargs {shlex.quote(brain.paths.ME)} ask again'), 'deny')
        self.assertEqual(self.gate(f'printf again | xargs {shlex.quote(brain.paths.ME)} ask'), 'deny')
        self.assertEqual(self.gate(f'echo ready && env {shlex.quote(brain.paths.ME)} ask again'), 'deny')
        self.assertEqual(self.gate(f'python3 {shlex.quote(brain.paths.ME)} --hands see Notes'), 'allow')
        self.assertEqual(self.gate(f'A={shlex.quote(brain.paths.ME)}; $A --front Fixture && $A --hands see Fixture'), 'allow')
        self.assertEqual(self.gate(f'A={shlex.quote(brain.paths.ME)}; $A ask again'), 'deny')
        self.assertEqual(self.gate('osascript -e \'tell application "Notes" to activate\''), 'deny')
        for separator in (';', '&&', '|', '\n', '\n\n'):
            with self.subTest(separator=separator):
                self.assertEqual(self.gate('true' + separator + 'open -a Fixture'), 'deny')
                self.assertEqual(self.gate('true' + separator + 'open -g -a Fixture'), 'allow')
        self.assertEqual(self.gate('open -a Notes'), 'deny')
        self.assertEqual(self.gate('env open -a Notes'), 'deny')
        self.assertEqual(self.gate('xargs open -a Notes'), 'deny')
        self.assertEqual(self.gate('printf Notes | xargs open -a'), 'deny')
        self.assertEqual(self.gate('xargs open -g -a Notes'), 'allow')
        self.assertEqual(self.gate('open -g -a Notes'), 'allow')
        self.assertEqual(self.gate('echo open'), 'allow')
        self.assertEqual(self.gate('printf open'), 'allow')
        self.assertEqual(self.gate(f'{brain.paths.HANDS} type Field activate'), 'allow')
        self.assertEqual(self.gate(f'{brain.paths.HANDS} type Field rabik.py'), 'allow')
        self.assertFalse(brain.macos.wants_focus('Do not show the window, just tell me whether it is open'))
        self.assertFalse(brain.macos.wants_focus('Do not open Notes; add a note'))
        self.assertFalse(brain.macos.wants_focus("Don't focus Notes"))
        self.assertFalse(brain.macos.wants_focus('Open Notes in the background'))
        brain.agents.save_request(os.environ['RABIK_ASK'], 'Show Notes')
        self.assertEqual(self.gate('osascript -e \'tell application "Notes" to activate\''), 'allow')
        self.assertEqual(self.gate('printf Notes | xargs open -a'), 'allow')

    def test_one_helper_targets_every_app_and_records_last_window(self):
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(self.target))) as run:
            for app in ['Spotify', 'Notes', 'Reminders', 'Finder']:
                brain.macos.preview_commands(f'osascript -e \'tell application "{app}" to make new item\'')
                self.assertEqual(run.call_args.args[0], [brain.paths.APP, '--window-target', app, ''])
        self.assertEqual(json.loads(Path(brain.paths.WORKED).read_text())['window'], 'Fixture')
        self.assertEqual(len(list(Path(os.environ['RABIK_ASK']).glob('hands-*'))), 4)

    def test_background_open_handles_apps_files_and_schemes(self):
        with patch.object(brain.macos, 'front', return_value=('Editor', 'Work')), patch.object(brain.macos, 'osa', return_value='Editor'), patch.object(brain.macos, 'preview_app',return_value=None) as preview, patch.object(time, 'sleep'), patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Notes.app')) as run:
            brain.web.show('Notes', bg=True)
            self.assertEqual(run.call_args.args[0], ['open', '-g', '-a', 'Notes'])
            preview.assert_called_with('Notes', 'open')
            self.assertFalse(any('set frontmost' in str(c) for c in brain.macos.osa.call_args_list))   # Notes stayed behind: nothing to give back
            brain.web.show('spotify:search:jazz', bg=True)
            self.assertEqual(run.call_args.args[0], ['open', '-g', 'spotify:search:jazz'])
            brain.web.show(os.environ['RABIK_ASK'], bg=True)
            self.assertEqual(run.call_args.args[0], ['open', '-g', os.environ['RABIK_ASK']])

    def test_safari_web_emits_preview_without_raising(self):
        with patch.dict(os.environ, {'RABIK_FRONT': 'Safari'}), patch.object(brain.web, 'browser_adapter',return_value='webkit'), patch.object(brain.macos, 'preview_app',return_value=None) as preview, patch.object(brain.hands,'hands_map',return_value=None), patch.object(subprocess, 'run', side_effect=lambda args,**kw:subprocess.CompletedProcess([], 0, '10\t2' if 'return (id of window' in args[2] else 'Fixture, 0, 0, 300, 200' if 'get {name, bounds}' in args[2] else 'page', '')) as run:
            self.assertEqual(brain.web.web('read'), 'page')
            preview.assert_called_once_with('Safari', 'read', title='Fixture', frame=[0,0,300,200])
            self.assertNotIn('activate', run.call_args.args[0][2])

    def test_blocked_fetch_can_read_the_named_url_in_a_background_browser_with_preview(self):
        class Blocked(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(503);self.end_headers();self.wfile.write(b'Fetch blocked')
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Blocked);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url=f'http://127.0.0.1:{server.server_port}/requested-page'
        with self.assertRaises(urllib.error.HTTPError) as failure:brain.web.get(url)
        self.assertEqual(failure.exception.code,503)
        def result(args,**kw):
            if 'make new tab' in args[2]:
                self.assertIn('set priorSelection to current tab of w',args[2])
                self.assertIn('set current tab of w to priorSelection',args[2])
            return subprocess.CompletedProcess([],0,'10\t2\t\n' if 'make new tab' in args[2] else 'Requested page, 0, 0, 300, 200' if 'get {name, bounds}' in args[2] else
                                               json.dumps({'signature':url+'|ready'}) if '"ready", ' in args[-1][-35:] else 'Actual requested page content', '')
        with patch.object(brain.web,'browser_adapter',return_value='webkit'), patch.object(brain.web,'page_ready',return_value=True), \
             patch.object(brain.macos,'preview_app',return_value=self.target),patch.object(brain.hands,'hands_map'),patch.object(brain.protocol,'emit') as emit,patch.object(subprocess,'run',side_effect=result):
            self.assertIn('Actual requested page content',brain.web.web('read',url,app='Fixture browser'))
            self.assertTrue(any(line.startswith('▣ ') for call in emit.call_args_list for line in call.args[0]))
        with patch.object(brain.web,'show') as show:
            self.assertIn('without credentials',brain.web.web('read','https://user:secret@fixture.example'))
            show.assert_not_called()
        with patch.object(brain.web,'browser_adapter',return_value='webkit'),patch.object(brain.web,'page_ready',return_value=False),patch.object(subprocess,'run',side_effect=result),patch.object(brain.macos,'preview_app'):
            self.assertIn('Requested page not ready',brain.web.web('read',url,app='Fixture browser'))

    def test_restore_does_not_interrupt_a_new_unrelated_app(self):
        with patch.object(brain.macos, 'osa', return_value='Editor') as osa:
            brain.macos.restore_focus('Finder', 'make a note', ['tell application "Notes" to make new note'])
            self.assertEqual(osa.call_count, 1)

    def test_restore_ignores_a_window_an_earlier_task_worked_in(self):
        Path(brain.paths.WORKED).write_text(json.dumps({'app': 'Editor', 'window': 'Draft'}))
        started = os.path.getmtime(brain.paths.WORKED)
        for start, calls in ((started + 1, 1), (started, 2)):   # written before this ask began: the user switched there themselves
            with self.subTest(start=start), patch.dict(brain.turn.TURN, {'_started': start}), patch.object(brain.macos, 'osa', return_value='Editor') as osa:
                brain.macos.restore_focus('Finder', 'what time is it', [])
                self.assertEqual(osa.call_count, calls)

    def test_work_mode_covers_non_browser_apps(self):
        for mode in ('back', 'front'):
            with self.subTest(mode=mode), patch.object(brain.prefs, 'pref', side_effect=lambda k, d: mode if k == 'workIn' else d), \
                 patch.object(brain.macos, 'osa', return_value='Editor') as osa, patch.object(brain.macos, 'preview_app', return_value={'app': 'Fixture'}), \
                 patch.object(brain.windows, 'keep_behind') as behind, patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertEqual(brain.web.show('Fixture', bg=True), 'opened Fixture ' + ('in front' if mode == 'front' else 'in the background'))
                self.assertEqual(run.call_args.args[0], ['open'] + ([] if mode == 'front' else ['-g']) + ['-a', 'Fixture'])
                self.assertEqual(behind.call_count, int(mode == 'back'))
                osa.reset_mock()
                osa.return_value = 'Fixture'
                brain.macos.restore_focus('Editor', 'work in Fixture', ['tell application "Fixture" to work'])
                self.assertEqual(osa.call_count, 0 if mode == 'front' else 2)

    def test_preview_passes_explicit_focus_intent_to_native_apps(self):
        for requested in (False, True):
            with self.subTest(requested=requested), patch.object(brain.macos, 'wants_focus', return_value=requested), \
                 patch.object(brain.protocol, 'emit'), patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(self.target))) as run:
                brain.macos.preview_app('Fixture')
                self.assertEqual(run.call_args.kwargs['env']['RABIK_FOCUS_REQUESTED'], '1' if requested else '0')

    def test_explicit_focus_is_not_undone_by_the_shared_fallback(self):
        with patch.dict(os.environ, {'RABIK_REQUEST': 'focus Fixture'}), patch.object(brain.macos, 'osa') as osa:
            brain.windows.keep_behind('Editor', 'Fixture')
            osa.assert_not_called()

    def test_agent_reads_reuse_one_own_window_and_close_it_at_task_end(self):
        scripts=[]; url=['']
        def result(args,**kw):
            if args[0]=='pgrep': return subprocess.CompletedProcess(args,0)
            self.assertEqual(args[0],'osascript'); script=args[2]; scripts.append(args)
            self.assertNotRegex(script,r'(?i)activate|AXRaise|frontmost|keystroke|key code')
            if 'make new tab' in script: return subprocess.CompletedProcess(args,0,'77\t'+str(len(scripts))+('\tnew' if args[-1]=='0' else '\t'),'')
            if 'get {name, bounds}' in script: out='Fixture, 0, 0, 300, 200'
            elif 'close window' in script: out=''
            else:
                self.assertIn('window id 77',script)
                out=json.dumps({'signature':url[0]+'|ready'}) if '"ready", ' in args[-1][-35:] else 'page text'
            return subprocess.CompletedProcess(args,0,out,'')
        with patch.dict(os.environ,{'RABIK_AGENT':'fixture'}),patch.object(brain.web,'browser_adapter',return_value='chromium'),patch.object(brain.web,'page_ready',return_value=True), \
             patch.object(brain.macos,'preview_app',return_value=None),patch.object(brain.hands,'hands_map'),patch.object(brain.macos,'osa',return_value='Editor'), \
             patch.object(brain.windows,'keep_behind') as behind,patch.object(subprocess,'run',side_effect=result):
            for i in range(2):
                url[0]='https://fixture.example/'+str(i)
                self.assertIn('page text',brain.web.web('read',url[0],app='Fixture Browser'))
            first,second=[a for a in scripts if 'make new tab' in a[2]]
            self.assertEqual((first[-1],second[-1]),('0','77'))   # the second page reuses the task's window
            self.assertIn('make new window',first[2]);self.assertIn('set index of prior to 1',first[2])
            behind.assert_called_once_with('Editor','Fixture Browser',wait=.5)
            saved=Path(brain.paths.agent_gate_dir(os.environ['RABIK_ASK']),'browser-window.json')
            self.assertEqual(json.loads(saved.read_text()),{'app':'Fixture Browser','window':77});self.assertEqual(saved.stat().st_mode&0o777,0o600)
            brain.web.close_agent_window(os.environ['RABIK_ASK'])
            self.assertIn('close window id 77',scripts[-1][2]);self.assertFalse(saved.exists())
            count=len(scripts);brain.web.close_agent_window(os.environ['RABIK_ASK']);self.assertEqual(len(scripts),count)   # never a window it did not open

    def test_agent_site_placement_uses_main_open_path_only_when_requested(self):
        url = 'https://unseen.example/catalog'
        with patch.dict(os.environ, {'RABIK_AGENT': 'fixture'}), \
             patch.object(brain.prefs, 'pref', side_effect=lambda k, d: 'front' if k == 'workIn' else d), \
             patch.object(brain.web, 'show', return_value='opened ' + url + ' in front') as show, \
             patch.object(brain.web, 'browser_adapter', return_value=''):
            brain.web.web('read', url, app='Unseen Browser')
            show.assert_called_once_with(url, bg=True)
            self.assertTrue(brain.macos.wants_focus(sites=True))
            self.assertFalse(brain.macos.wants_focus('Show this browser'))
            brain.agents.save_request(os.environ['RABIK_ASK'], 'Research in the background')
            show.reset_mock()
            brain.web.web('read', url, app='Unseen Browser')
            show.assert_not_called()

    def test_agent_show_in_front_does_not_reenter_url_reader(self):
        with patch.dict(os.environ, {'RABIK_AGENT': 'fixture'}), \
             patch.object(brain.paths, 'DIR', os.environ['RABIK_ASK']), \
             patch.object(brain.prefs, 'pref', side_effect=lambda k, d: 'front' if k == 'workIn' else d), \
             patch.object(brain.macos, 'osa', return_value='Fixture Editor'), \
             patch.object(brain.macos, 'preview_app', return_value={'app': 'Unseen Browser'}), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run, \
             patch.object(brain.web, 'web', return_value='Page ready.') as web:
            self.assertIn('in front', brain.web.show('https://unseen.example', bg=True))
            self.assertIn(unittest.mock.call(['open', 'https://unseen.example']), run.call_args_list)
            web.assert_called_once_with('wait', text='https://unseen.example', app='Unseen Browser', fresh=True)

    def test_agent_background_show_and_window_reads_preserve_their_pin(self):
        Path(os.environ['RABIK_ASK'],'window-summary.json').write_text(json.dumps({'app':'Fixture Browser','web':True}))
        with patch.dict(os.environ,{'RABIK_AGENT':'fixture'}),patch.object(brain.web,'web',return_value='Page\nControls:') as web:
            brain.web.show('https://fixture.example')
            web.assert_called_with('read','https://fixture.example')
            brain.screen.window_text('Fixture Browser')
            web.assert_called_with('read',app='Fixture Browser',fresh=False)

    def test_agent_front_stays_background_and_show_respects_user_intent(self):
        with patch.dict(os.environ, {'RABIK_AGENT': 'fixture'}), patch.object(brain.macos, 'preview_app',return_value=None) as preview, patch.object(brain.hands, 'hands_map', return_value={'description': 'Notes map'}) as mapped, \
             patch.object(brain.macos, 'window_target', return_value=self.target), patch.object(brain.screen, 'look', return_value=[('/fake.jpg', 'Screen 1')]) as looked, \
             patch.object(brain.macos, 'osa') as osa, patch('sys.argv', ['rabik.py', '--front', 'Notes', '--asked']), patch('sys.stdout', new_callable=io.StringIO) as out:
            brain.cli.main()   # the model's --asked never brings an agent forward: only the user's words do
            osa.assert_not_called(); self.assertEqual(out.getvalue().strip(), 'Notes map\nScreen 1: /fake.jpg')
            preview.assert_called_once(); mapped.assert_called_once_with('Notes', target=self.target); looked.assert_called_once_with(cleanup=False, window=self.target)
        with patch.object(brain.web, 'show') as show, patch('sys.stdout', new_callable=io.StringIO), patch('sys.argv', ['rabik.py', '--show', 'Notes']):
            brain.cli.main(); show.assert_called_with('Notes', True)
            brain.agents.save_request(os.environ['RABIK_ASK'], 'Open Notes')
            brain.cli.main(); show.assert_called_with('Notes', False)

    def test_agent_front_work_follows_only_the_users_words_and_uses_the_real_path(self):
        self.assertTrue(brain.macos.asks_front('fill the form in front of me') and brain.macos.asks_front('do it in the foreground'))
        self.assertFalse(brain.macos.asks_front('fill the form in the background'))
        agents = brain.agents.Agents(emit=lambda event: None)
        def started(words=None, brief='Open Keynote and show the deck', **extra):
            row = agents.new(); row.update(brief=brief, status='offered', **({'request': words} if words else {}), **extra); agents.rows[row['id']] = row
            agents.start(row['id'])
            return row, Path(brain.paths.agent_gate_dir(row['directory']), 'focus-requested')
        with patch.object(agents, 'warm'), patch.object(agents, 'send'), patch.object(agents, 'save'):
            self.assertFalse(started('Research flights to Lisbon')[1].exists())
            self.assertFalse(started()[1].exists())   # a model-written brief alone never brings an agent forward
            self.assertTrue(started('keep going', focus=True)[1].exists())   # a moved ask that already worked in front
            row, marker = started('Build the deck in Keynote and show it to me in front')
        self.assertTrue(marker.exists())
        with patch.dict(os.environ, {'RABIK_AGENT': row['id'], 'RABIK_ASK': row['directory']}):
            self.assertTrue(brain.macos.wants_focus())
            with patch.object(brain.macos, 'osa') as osa, patch.object(brain.macos, 'free_focus'), patch.object(brain.screen, 'look', return_value=[('/fake.jpg', 'Screen')]), \
                 patch.object(time, 'sleep'), patch('sys.stdout', new_callable=io.StringIO), patch('sys.argv', ['rabik.py', '--front', 'Keynote']):
                brain.cli.main()
                osa.assert_any_call('tell application "Keynote" to activate')
            marker.unlink(); Path(row['directory'], 'focus-requested').touch()   # the agent's own folder is writable by the agent: it does not count
            self.assertFalse(brain.macos.wants_focus())
        brain.agents.save_request(os.environ['RABIK_ASK'], 'open Keynote and build three slides')
        move = brain.handoffs.MainMove('Request: open Keynote and build three slides', type('Worker', (), {'ask': os.environ['RABIK_ASK']})())
        self.assertTrue(move.handoff()['focus'])

    def test_front_carries_model_intent_in_any_language(self):
        marker = Path(os.environ['RABIK_ASK'], 'focus-requested')
        with patch.object(shutil, 'which', return_value='/fake/claude'), \
             patch.object(subprocess, 'Popen') as popen, patch.object(signal, 'signal'), \
             patch.object(atexit, 'register'):
            worker = brain.clients.start_claude()
            self.assertEqual(worker.ask, os.environ['RABIK_ASK'])
            self.assertEqual(popen.call_args.kwargs['env']['RABIK_ASK'], worker.ask)
            worker.errors.close()
        for request in ('메모 앱 열어줘', '打开微信'):
            with self.subTest(request=request):
                marker.unlink(missing_ok=True)
                brain.agents.save_request(os.environ['RABIK_ASK'], request)
                self.assertFalse(brain.macos.wants_focus())
                with patch.object(brain.macos, 'osa') as osa, patch.object(brain.macos, 'free_focus') as free, patch.object(brain.macos, 'window_target', return_value=self.target), \
                     patch.object(brain.screen, 'look', return_value=[('/fake.jpg', 'Screen')]), \
                     patch.object(time, 'sleep'), patch('sys.stdout', new_callable=io.StringIO) as out, \
                     patch('sys.argv', ['rabik.py', '--front', 'Fixture']):
                    brain.cli.main()   # no focus words found (they are English-only): a picture in place, and how to say the user asked
                    osa.assert_not_called(); self.assertIn(f'{shlex.quote(brain.paths.ME)} --front Fixture --asked', out.getvalue())
                    with patch('sys.argv', ['rabik.py', '--front', 'Fixture', '--asked']): brain.cli.main()
                    osa.assert_called_once_with('tell application "Fixture" to activate')
                    free.assert_called_once_with(user=True)
                self.assertTrue(brain.macos.wants_focus(request))
                with patch.object(brain.macos, 'free_focus') as free, patch.object(brain.macos, 'osa') as osa:
                    brain.macos.allow_focus(request)
                    free.assert_called_once_with(user=True)
                    brain.macos.restore_focus('Editor', request, ['Fixture'])
                    osa.assert_not_called()
                with patch.object(subprocess, 'Popen') as popen:
                    popen.return_value.communicate.return_value = ('', '')
                    brain.hands.hands_call(['see'])
                    self.assertEqual(popen.call_args.kwargs['env']['RABIK_FOCUS_REQUESTED'], '1')
                marker.unlink(missing_ok=True)   # this fixture's agent gate folder is the ask folder itself
                with patch.dict(os.environ, {'RABIK_AGENT': 'fixture'}):
                    self.assertFalse(brain.macos.wants_focus())
                    self.assertTrue(brain.macos.wants_focus(sites=True))

    def test_front_works_on_a_window_in_any_state_without_raising_it(self):
        # Oct 21: a page on his second display, not key, was raised by --front although he kept working on the laptop. Any app, any state.
        marker = Path(os.environ['RABIK_ASK'], 'focus-requested')
        unfocused, covered, minimized = {**self.target, 'visible': True}, {**self.target, 'visible': False}, {**self.target, 'minimized': True}
        for request, target, extra, raised in (('play it', unfocused, [], False), ('play it', covered, [], False), ('keep going', minimized, [], True),
                                               ('play it', {}, [], True), ('show me it', unfocused, [], True), ('play it', unfocused, ['--asked'], True)):
            with self.subTest(request=request, target=target, extra=extra):
                brain.agents.save_request(os.environ['RABIK_ASK'], request); marker.unlink(missing_ok=True)
                with patch.object(brain.macos, 'window_target', return_value=target), patch.object(brain.macos, 'osa') as osa, \
                     patch.object(brain.macos, 'free_focus') as free, patch.object(brain.screen, 'look', return_value=[('/fake.jpg', 'Screen 2')]) as looked, \
                     patch.object(time, 'sleep'), patch('sys.stdout', new_callable=io.StringIO) as out, \
                     patch('sys.argv', ['rabik.py', '--front', 'Fixture App', 'Board', *extra]):
                    brain.cli.main()
                self.assertEqual(osa.called, raised); self.assertEqual(free.called, raised); self.assertEqual(marker.exists(), raised)
                self.assertIn('Screen 2: /fake.jpg', out.getvalue())
                if not raised:
                    looked.assert_called_once_with(cleanup=False, window=target)   # the window itself, painted where it sits
                    self.assertIn("--front 'Fixture App' Board --asked", out.getvalue())
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(covered), '')) as run:
            self.assertEqual(brain.macos.window_target('Fixture App', 'Board'), covered)
            self.assertEqual(run.call_args.args[0], [brain.paths.APP, '--window-target', 'Fixture App', 'Board'])
            self.assertEqual(run.call_args.kwargs['env']['RABIK_FOCUS_REQUESTED'], '0')   # the lookup itself never activates
        for failure in (OSError(), subprocess.TimeoutExpired('x', 2)):
            with patch.object(subprocess, 'run', side_effect=failure): self.assertEqual(brain.macos.window_target('Fixture App'), {})
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '[]', '')): self.assertEqual(brain.macos.window_target('Fixture App'), {})
        self.assertIn('pictures that window in place, even covered; raises only if asked.', brain.prompts.system_prompt(brain.prompts.ASK_FIRST))
        with patch.object(brain.prefs, 'pref', side_effect=lambda k, d: 'front' if k == 'workIn' else d):
            self.assertNotIn('pictures that window in place', brain.prompts.system_prompt(brain.prompts.ASK_FIRST))

    def test_look_paints_the_target_window_on_its_own_display(self):
        calls = []
        def run(cmd, **_):
            calls.append(cmd)
            if cmd[:2] == [brain.paths.APP, '--look']: Path(cmd[3]).write_bytes(b'jpg')
            return subprocess.CompletedProcess(cmd, 0, 'window\n' if len(cmd) == 5 and painted[0] else '', '')
        painted = [True]
        displays = [('Built-in', 0, 0, 1512, 982, True), ('Monitor', 1512, 0, 2560, 1440, False)]
        window = {**self.target, 'app': 'Fixture App', 'window': 'Board', 'windowFrame': [1900, 200, 1100, 800], 'visible': False}
        with patch.object(brain.macos, 'screens', return_value=displays), patch.object(subprocess, 'run', side_effect=run), \
             patch.object(brain.prefs, 'pref', side_effect=lambda k, d: False if k == 'draw' else d):
            shots = brain.screen.look(cleanup=False, window=window)
            self.assertEqual([c[:3] + c[4:] for c in calls], [[brain.paths.APP, '--look', '2', '42']])   # only its display, with its window id
            self.assertEqual(len(shots), 1)
            self.assertIn('Fixture App "Board" painted where it sits (hidden from the user); click spots as 2:x,y', shots[0][1])
            painted[0] = False; calls.clear()   # the window could not be captured: the label never claims it
            self.assertNotIn('painted', brain.screen.look(cleanup=False, window=window)[0][1])
            calls.clear()
            labels = [label for _, label in brain.screen.look(cleanup=False)]
            self.assertEqual(len(calls), 2); self.assertTrue(labels[0].endswith('click spots as 1:x,y in picture pixels)'))
        for path in Path(os.environ['RABIK_ASK']).glob('rabik-screen-*'): path.unlink()

    def test_old_foreground_shortcuts_upgrade_to_background_open(self):
        saved={'cmds':['open -a Notes'],'reply':'Done.'}
        with patch.object(brain.skills,'skills',return_value={'study':saved}),patch.object(brain.web,'show',return_value='opened Notes in the background') as show:
            self.assertEqual(brain.skills.replay('study').reply,'Done.');show.assert_called_once_with('Notes',True)

    def test_open_preview_expands_shell_home_and_restore_uses_current_app(self):
        with patch.object(brain.macos,'preview_app') as preview:
            brain.macos.preview_commands('open -g ~/Documents/fixture.pdf')
            preview.assert_called_with(os.path.expanduser('~/Documents/fixture.pdf'),'open',directory=None)
        with patch.dict(os.environ,{'RABIK_FRONT':'Old Mail'}),patch.object(brain.macos,'osa',side_effect=['Editor','com.fixture.browser','Browser','Browser','']) as osa,patch.object(brain.macos,'preview_app',return_value={'app':'Browser'}),patch.object(time,'sleep'),patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
            brain.web.show('https://fixture.invalid',bg=True)
            self.assertEqual(osa.call_args.args[1],'Editor')

    def test_browser_preview_stays_with_the_pinned_window_after_focus_changes(self):
        with patch.dict(os.environ,{'RABIK_FRONT':'Google Chrome'}),patch.object(brain.web,'browser_adapter',return_value='chromium'),patch.object(brain.macos,'preview_app',return_value=self.target) as preview,patch.object(brain.web,'page_ready',return_value=True),patch.object(brain.hands,'hands_map',return_value=None),patch.object(brain.protocol,'emit') as emit,patch.object(subprocess,'run',side_effect=[subprocess.CompletedProcess([],0,'41\t73',''),subprocess.CompletedProcess([],0,'Fixture, 0, 0, 300, 200',''),subprocess.CompletedProcess([],0,'Page',''),subprocess.CompletedProcess([],0,'Filled',''),subprocess.CompletedProcess([],0,'Current field value',''),subprocess.CompletedProcess([],0,'Fixture, 10, 20, 410, 320',''),subprocess.CompletedProcess([],0,'Reread','')]) as run:
            brain.web.web('read');brain.web.web('fill','2','Text');brain.web.web('read')
        self.assertIn('window id 41 whose id is 73',run.call_args.args[0][2])
        self.assertEqual(preview.call_args_list, [unittest.mock.call('Google Chrome','read',title='Fixture',frame=[0,0,300,200]),unittest.mock.call('Google Chrome','read',title='Fixture',frame=[10,20,400,300])])
        target=json.loads(emit.call_args.args[0][0][2:]);self.assertEqual(target['windowID'],'42');self.assertEqual(target['action'],'read')

    def test_applescript_ids_and_named_windows_use_the_same_target_helper(self):
        with patch.object(brain.macos,'preview_app') as preview:
            brain.macos.preview_commands('osascript -e \'tell application id "com.apple.Notes" to set name of window "Pilot" to "Pilot"\'')
            preview.assert_called_once_with('com.apple.Notes',title='Pilot',directory=None)
