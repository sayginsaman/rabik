"""Page readiness uses fake browser calls and a controlled clock; no real apps or paid calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import atticus


class PageReadyTests(unittest.TestCase):
    def test_background_page_reuses_only_its_unchanged_tab_for_both_protocols(self):
        for adapter, target in [('chromium', 'first tab of window id 10 whose id is 2'), ('webkit', 'tab 2 of window id 10')]:
            with self.subTest(adapter=adapter), tempfile.TemporaryDirectory() as scratch:
                Path(scratch, 'background-page.json').write_text(json.dumps(
                    {'app': 'Browser Fixture', 'adapter': adapter, 'window': 10, 'tab': 2, 'url': 'https://old.invalid/'}))
                with patch.object(atticus, 'DIR', scratch), patch.dict(os.environ, {'ATTICUS_ASK': scratch}), \
                     patch.object(atticus, 'browser_adapter', return_value=adapter), \
                     patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
                    self.assertTrue(atticus.background_tab('https://new.invalid/', 'Browser Fixture'))
                self.assertIn(target, run.call_args.args[0][2])
                self.assertIn('Atticus page changed', run.call_args.args[0][2])
                self.assertEqual(run.call_args.args[0][-2:], ['https://old.invalid/', 'https://new.invalid/'])
                page = json.loads(Path(scratch, 'web.json').read_text())
                self.assertEqual((page['window'], page['tab'], page['target']), (10, 2, None))
                self.assertEqual(Path(scratch, 'web.json').stat().st_mode & 0o777, 0o600)

    def test_background_page_changed_by_the_user_is_not_reused(self):
        with tempfile.TemporaryDirectory() as scratch:
            Path(scratch, 'background-page.json').write_text(json.dumps(
                {'app': 'Browser Fixture', 'adapter': 'chromium', 'window': 10, 'tab': 2, 'url': 'https://old.invalid/'}))
            refused = subprocess.CompletedProcess([], 1, '', 'Atticus page changed')
            with patch.object(atticus, 'DIR', scratch), patch.dict(os.environ, {'ATTICUS_ASK': scratch}), \
                 patch.object(atticus, 'browser_adapter', return_value='chromium'), patch.object(atticus.subprocess, 'run', return_value=refused):
                self.assertFalse(atticus.background_tab('https://new.invalid/', 'Browser Fixture'))
            self.assertFalse(Path(scratch, 'web.json').exists())

    def test_background_show_navigates_the_dedicated_tab_without_opening_another(self):
        handler = subprocess.CompletedProcess([], 0, 'Browser Fixture\n', '')
        with patch.dict(os.environ, {'ATTICUS_FOCUS_GUARD': '1'}), patch.object(atticus.subprocess, 'run', return_value=handler) as run, \
             patch.object(atticus, 'background_tab', return_value=True), patch.object(atticus, 'remember_background_tab') as remember, \
             patch.object(atticus, 'web', return_value='Page ready.') as web:
            self.assertEqual(atticus.show('https://fixture.invalid', bg=True), 'opened https://fixture.invalid in the background')
        self.assertEqual(run.call_args_list, [unittest.mock.call([atticus.APP, '--target-app', 'https://fixture.invalid'], capture_output=True, text=True, timeout=1)])
        web.assert_called_once_with('wait', text='https://fixture.invalid', app='Browser Fixture')
        remember.assert_called_once_with('Browser Fixture')

    def test_scriptable_page_adapter_is_probed_and_cached_without_an_app_list(self):
        with tempfile.TemporaryDirectory() as scratch:
            def worker(args, **kwargs):
                if args[:2] == ['pgrep', '-xq']: return subprocess.CompletedProcess(args, 0, '', '')
                script = args[2]
                if script.startswith('id of application'): return subprocess.CompletedProcess(args, 0, 'org.fixture.nebula\n', '')
                if 'return (id of window' in script: return subprocess.CompletedProcess(args, 0, '10\t2', '')
                return subprocess.CompletedProcess(args, 0, '{"ready":true,"signature":"fixture"}', '')
            with patch.object(atticus, 'DIR', scratch), patch.object(atticus.subprocess, 'run', side_effect=worker) as run:
                self.assertEqual(atticus.browser_adapter('Nebula'), 'chromium')
                calls = run.call_count
                self.assertEqual(atticus.browser_adapter('Nebula'), 'chromium')
            self.assertEqual(run.call_count, calls + 2)   # running + bundle-id lookup only; no protocol probe
            cache = json.loads(Path(scratch, 'web-capabilities.json').read_text())
            self.assertEqual(cache['org.fixture.nebula'], 'chromium')

    def test_adapter_never_events_a_stopped_app_or_caches_permission_denials(self):
        with tempfile.TemporaryDirectory() as scratch:
            with patch.object(atticus, 'DIR', scratch), patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')) as run:
                self.assertEqual(atticus.browser_adapter('Stopped Fixture'), '')
            self.assertEqual(run.call_args.args[0], ['pgrep', '-xq', 'Stopped Fixture'])
            self.assertFalse(Path(scratch, 'web-capabilities.json').exists())

            probes = []
            def worker(args, **kwargs):
                if args[:2] == ['pgrep', '-xq']: return subprocess.CompletedProcess(args, 0, '', '')
                script = args[2]; probes.append(script)
                if script.startswith('id of application'): return subprocess.CompletedProcess(args, 0, 'org.fixture.native\n', '')
                if 'return (id of window' in script: return subprocess.CompletedProcess(args, 0, '10\t2', '')
                return subprocess.CompletedProcess(args, 1, '', 'Not allowed to send Apple events')
            with patch.object(atticus, 'DIR', scratch), patch.object(atticus.subprocess, 'run', side_effect=worker):
                self.assertEqual(atticus.browser_adapter('Native Fixture'), '')
                count = len(probes)
                self.assertEqual(atticus.browser_adapter('Native Fixture'), '')
            self.assertGreater(len(probes), count + 1)
            self.assertFalse(Path(scratch, 'web-capabilities.json').exists())

    def test_any_javascript_permission_message_identifies_a_disabled_adapter(self):
        with tempfile.TemporaryDirectory() as scratch:
            def worker(args, **kwargs):
                if args[:2] == ['pgrep', '-xq']: return subprocess.CompletedProcess(args, 0, '', '')
                script = args[2]
                if script.startswith('id of application'): return subprocess.CompletedProcess(args, 0, 'org.fixture.browser\n', '')
                if 'return (id of window' in script: return subprocess.CompletedProcess(args, 0, '10\t2', '')
                return subprocess.CompletedProcess(args, 1, '', 'You must enable Allow JavaScript from Apple Events')
            with patch.object(atticus, 'DIR', scratch), patch.object(atticus.subprocess, 'run', side_effect=worker):
                self.assertEqual(atticus.browser_adapter('Browser Fixture'), 'chromium')

    def test_window_query_permission_denial_is_retried_later(self):
        with tempfile.TemporaryDirectory() as scratch:
            def worker(args, **kwargs):
                if args[:2] == ['pgrep', '-xq']: return subprocess.CompletedProcess(args, 0, '', '')
                if args[2].startswith('id of application'): return subprocess.CompletedProcess(args, 0, 'org.fixture.browser\n', '')
                return subprocess.CompletedProcess(args, 1, '', 'Not authorized to send Apple events')
            with patch.object(atticus, 'DIR', scratch), patch.object(atticus.subprocess, 'run', side_effect=worker) as run:
                self.assertEqual(atticus.browser_adapter('Browser Fixture'), '')
                first = run.call_count
                self.assertEqual(atticus.browser_adapter('Browser Fixture'), '')
            self.assertGreater(run.call_count, first + 2)
            self.assertFalse(Path(scratch, 'web-capabilities.json').exists())

    def test_label_hides_flags_query_and_chained_commands(self):
        for tail in ('', ' && sleep 3 && '+atticus.WEB+' read', '; '+atticus.WEB+' read'):
            self.assertEqual(atticus.label('Bash',{'command':atticus.SHOW+' --bg "https://www.amazon.com/s?k=epsom+salt"'+tail}),'Opening amazon.com')
        self.assertEqual(atticus.label('Bash',{'command':atticus.SHOW+' --bg "/tmp/Fixture Notes.md" && echo ok'}),'Opening Fixture Notes.md')
        # real log chains: the label names this command's target, never a later helper or its quoted words
        self.assertEqual(atticus.label('Bash',{'command':f'A={atticus.ME}; $A --front Orca && $A --hands click "atticus"'}),'Bringing Orca forward')
        self.assertEqual(atticus.label('Bash',{'command':'open -g -a Spotify && '+atticus.ME+' --queue "violet"'}),'Opening Spotify')
        self.assertEqual(atticus.label('Bash',{'command':'open "x-apple.systempreferences:sound" && '+atticus.HANDS+' see "System Settings"'}),'Opening x-apple.systempreferences:sound')

    def test_poll_waits_for_ready_and_stable_dom_with_a_five_second_cap(self):
        now=[0];seen=[]
        def sleep(seconds): now[0]+=seconds
        def read(timeout):
            seen.append(timeout);return json.dumps({'ready':now[0]>=.2,'signature':'loaded' if now[0]>=.3 else 'old'})
        with patch.object(atticus.time,'monotonic',side_effect=lambda:now[0]),patch.object(atticus.time,'sleep',side_effect=sleep):
            self.assertTrue(atticus.page_ready(read));self.assertLess(now[0],.7);self.assertGreaterEqual(now[0],.5)
            now[0]=0;self.assertFalse(atticus.page_ready(lambda timeout:json.dumps({'ready':False})));self.assertLessEqual(now[0],5.01)
        self.assertTrue(all(0<timeout<=.5 for timeout in seen))

    def test_an_already_loaded_other_tab_is_not_ready(self):
        now=[0]
        def sleep(seconds): now[0]+=seconds
        def read(timeout): return json.dumps({'ready':True,'signature':('https://mail.google.com/x|1' if now[0]<1 else 'https://www.amazon.com/s?k=x|2')})
        with patch.object(atticus.time,'monotonic',side_effect=lambda:now[0]),patch.object(atticus.time,'sleep',side_effect=sleep):
            self.assertTrue(atticus.page_ready(read,'https://amazon.com/s?k=x'));self.assertGreaterEqual(now[0],1)   # Gmail was loaded, but Amazon is what we opened

    def test_permission_error_is_not_hidden_by_polling(self):
        with patch.object(atticus.time,'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError,'blocks this'):atticus.page_ready(Mock(side_effect=RuntimeError('Browser blocks this. Enable JavaScript.')))
            sleep.assert_not_called()

    def test_background_url_waits_in_its_handler_browser(self):
        with patch.dict(os.environ,{'ATTICUS_FOCUS_GUARD':'1'}),patch.object(atticus.subprocess,'run',return_value=Mock(returncode=0)),patch.object(atticus,'preview_app',return_value={'app':'Safari'}),patch.object(atticus,'web',return_value='Page ready.') as web:
            self.assertEqual(atticus.show('https://fixture.invalid',bg=True),'opened https://fixture.invalid in the background')
        web.assert_called_once_with('wait',text='https://fixture.invalid',app='Safari',fresh=True)

    def test_read_after_open_keeps_the_handler_browser_instead_of_another_running_browser(self):
        with tempfile.TemporaryDirectory() as scratch,patch.dict(os.environ,{'ATTICUS_ASK':scratch,'ATTICUS_FRONT':'Google Chrome'}),patch.object(atticus,'browser_adapter',return_value='webkit'),patch.object(atticus,'page_ready',return_value=True),patch.object(atticus,'preview_app',return_value=None),patch.object(atticus,'hands_map',return_value=None),patch.object(atticus.subprocess,'run',side_effect=lambda args,**kw:subprocess.CompletedProcess([],0,'10\t2' if 'return (id of window' in args[2] else 'Fixture, 0, 0, 300, 200' if 'get {name, bounds}' in args[2] else 'Fixture page','')) as run:
            self.assertEqual(atticus.web('wait',app='Safari',fresh=True),'Page ready.')
            self.assertEqual(atticus.web('read'),'Fixture page')
            self.assertIn('in tab 2 of window id 10',run.call_args.args[0][2])
            self.assertNotIn('front document',run.call_args.args[0][2])
            self.assertEqual(sum('return (id of window' in c.args[0][2] for c in run.call_args_list),1)

    def test_agent_hands_and_later_previews_stay_on_the_pinned_page_window(self):
        target={'pid':123,'windowID':'77','windowFrame':[10,20,600,400],'window':'Work','app':'Browser Fixture'}
        with tempfile.TemporaryDirectory() as scratch:
            Path(scratch,'web.json').write_text(json.dumps({'app':'Browser Fixture','adapter':'webkit','window':10,'tab':2,'target':None}))
            process=Mock(returncode=0,args=[]);process.communicate.return_value=('mapped','');process.poll.return_value=0
            def browser(args,**kwargs):
                return subprocess.CompletedProcess(args,0,'Work, 10, 20, 610, 420' if 'get {name, bounds}' in args[2] else 'Fixture page','')
            with patch.dict(os.environ,{'ATTICUS_ASK':scratch,'ATTICUS_AGENT':'agent','ATTICUS_HANDS_STATE':str(Path(scratch,'hands.json'))}), \
                 patch.object(atticus,'browser_adapter',return_value='webkit'),patch.object(atticus,'preview_app',return_value=target), \
                 patch.object(atticus.subprocess,'run',side_effect=browser),patch.object(atticus.subprocess,'Popen',return_value=process) as popen:
                self.assertEqual(atticus.web('read'),'Fixture page')
            self.assertEqual(popen.call_args.kwargs['env']['ATTICUS_HANDS_WINDOW'],'77')
            Path(scratch,'hands.json').write_text(json.dumps(target))
            with patch.dict(os.environ,{'ATTICUS_AGENT':'agent','ATTICUS_HANDS_STATE':str(Path(scratch,'hands.json'))}), \
                 patch.object(atticus.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(target),'')) as run:
                atticus.preview_app('Browser Fixture')
            self.assertEqual(json.loads(run.call_args.args[0][-1]),target['windowFrame'])

    def test_agent_hands_stay_in_the_tasks_own_browser_window_or_fail(self):
        with tempfile.TemporaryDirectory() as scratch:
            Path(scratch,'browser-window.json').write_text(json.dumps({'app':'Browser Fixture','window':5}))
            Path(scratch,'hands.json').write_text(json.dumps({'app':'Browser Fixture','pid':9,'windowID':'31'}))   # last map: the user's window
            process=Mock(returncode=0,args=[]);process.communicate.return_value=('mapped','');process.poll.return_value=0;process.stdout.readline.return_value='mapped'
            def native(args,**kwargs):
                if args[0]=='osascript':
                    self.assertIn('window id 5',args[2]);return subprocess.CompletedProcess(args,0,'10, 20, 610, 420\n','')
                self.assertEqual(json.loads(args[-1]),[10,20,600,400]);return subprocess.CompletedProcess(args,0,json.dumps({'windowID':'88'}),'')
            env={'ATTICUS_ASK':scratch,'ATTICUS_AGENT':'agent','ATTICUS_HANDS_STATE':str(Path(scratch,'hands.json'))}
            with patch.dict(os.environ,env),patch.object(atticus.subprocess,'run',side_effect=native),patch.object(atticus.subprocess,'Popen',return_value=process) as popen, \
                 patch.object(atticus.select,'select',return_value=([1],[],[])):
                atticus.hands_call(['see','Browser Fixture']);atticus.hands_action(['click','Search'],lambda target:True)
            self.assertEqual([c.kwargs['env']['ATTICUS_HANDS_WINDOW'] for c in popen.call_args_list],['88','88'])
            with patch.dict(os.environ,env),patch.object(atticus.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','no such window')),patch.object(atticus.subprocess,'Popen') as popen:
                self.assertEqual(atticus.hands_call(['see','Browser Fixture']).stdout,atticus.GONE)
                self.assertEqual(atticus.hands_action(['click','Search'],lambda target:True)[1].stdout,atticus.GONE)
            popen.assert_not_called()

    def test_agent_look_maps_afresh_after_its_last_window_closed_and_other_apps_are_unpinned(self):
        with tempfile.TemporaryDirectory() as scratch:
            Path(scratch,'hands.json').write_text(json.dumps({'app':'Notes','pid':9,'windowID':'31'}))
            def process(code,out):
                p=Mock(returncode=code,args=[]);p.communicate.return_value=(out,'');p.poll.return_value=code;return p
            env={'ATTICUS_ASK':scratch,'ATTICUS_AGENT':'agent','ATTICUS_HANDS_STATE':str(Path(scratch,'hands.json'))}
            closed="This task's Notes window closed or changed. Nothing was done; run see again."
            with patch.dict(os.environ,env),patch.object(atticus.subprocess,'Popen',side_effect=[process(1,closed),process(0,'App: Notes'),process(0,'App: Safari'),process(1,closed)]) as popen:
                self.assertEqual(atticus.hands_call(['see','Notes']).stdout,'App: Notes')
                self.assertEqual(atticus.hands_call(['see','Safari']).stdout,'App: Safari')
                self.assertEqual(atticus.hands_call(['click','Done']).stdout,closed)   # an action never drifts to another window
            pins=[c.kwargs['env'].get('ATTICUS_HANDS_WINDOW') for c in popen.call_args_list]
            self.assertEqual(pins,['31',None,None,'31'])

    def test_agent_page_actions_stay_out_of_the_users_window(self):
        with tempfile.TemporaryDirectory() as scratch:
            Path(scratch,'web.json').write_text(json.dumps({'app':'Browser Fixture','adapter':'webkit','window':10,'tab':2,'target':None}))
            with patch.dict(os.environ,{'ATTICUS_ASK':scratch,'ATTICUS_AGENT':'agent'}),patch.object(atticus,'browser_adapter',return_value='webkit'), \
                 patch.object(atticus.subprocess,'run') as run:
                for cmd in ('click','fill','type-after'):
                    self.assertIn("user's own window",atticus.web(cmd,'1','text'))
            run.assert_not_called()

    def test_work_page_reuses_the_asks_page_else_finds_the_tab_or_window(self):
        with tempfile.TemporaryDirectory() as scratch:
            self.assertEqual(atticus.work_page(ask=scratch),{})   # nothing used, nothing named: no page
            Path(scratch,'web.json').write_text(json.dumps({'app':'Browser Fixture','adapter':'webkit','window':4,'tab':2,'target':{'x':1}}))
            used={'app':'Browser Fixture','adapter':'webkit','window':4,'tab':2,'title':'Form','url':'https://form.fixture.test/'}
            with patch.object(atticus,'osa',return_value='4\t2\tForm\thttps://form.fixture.test/') as osa,patch.object(atticus,'browser_adapter') as probe:
                self.assertEqual(atticus.work_page(ask=scratch),used)   # its URL too: the agent may act only while the tab stays on that site
                self.assertEqual(atticus.work_page('Browser Fixture',ask=scratch),used)
            probe.assert_not_called();self.assertEqual(osa.call_args.args[1:],('','4','2'));self.assertIn('tab ((item 3 of argv) as integer) of w',osa.call_args.args[0])
            with patch.object(atticus,'osa',return_value=''):
                self.assertEqual(atticus.work_page(ask=scratch),{'app':'Browser Fixture'})   # its tab closed: no page, never the front tab
            with patch.object(atticus,'browser_adapter',return_value='webkit'),patch.object(atticus,'osa',return_value='4\t3\tInbox\thttps://mail.fixture.test/') as osa:
                self.assertEqual(atticus.work_page('Browser Fixture','Inbox',scratch)['tab'],3)
            self.assertIn('current tab of w',osa.call_args.args[0]);self.assertIn('index of t',osa.call_args.args[0])
            with patch.object(atticus,'browser_adapter',return_value=''),patch.object(atticus,'proc_of',side_effect=lambda app:app), \
                 patch.object(atticus,'osa',return_value='Re: Lunch') as osa:
                self.assertEqual(atticus.work_page('Mail Fixture',ask=scratch),{'app':'Mail Fixture','title':'Re: Lunch'})
                Path(scratch,'hands.json.windows').write_text('{"123":["43"]}')
                with patch.object(atticus,'hands_state',return_value=str(Path(scratch,'hands.json'))):
                    self.assertEqual(atticus.work_page('Mail Fixture',ask=scratch)['windows'],{'123':['43']})   # the user's other window at ask time goes with the handoff
            with patch.object(atticus,'browser_adapter',return_value='chromium'),patch.object(atticus,'osa',return_value=''):
                self.assertEqual(atticus.work_page('Browser Two',ask=scratch),{'app':'Browser Two'})   # no window: no page to act on
            with patch.dict(os.environ,{'ATTICUS_FRONT':'Notes'}),patch.object(atticus,'wants_focus',return_value=False), \
                 patch.object(atticus,'osa',return_value='4\t2\tForm\thttps://form.fixture.test/'):
                moved=atticus.MainMove('Request: finish filling this form',type('Worker',(),{'ask':scratch})()).handoff()
            self.assertEqual((moved['app'],moved['page']),('Browser Fixture',used))   # a moved ask keeps the page it was working in

    def test_handed_app_resolves_the_name_as_said_to_the_running_app(self):
        native=lambda args,**kw:subprocess.CompletedProcess(args,0,'Fixture Browser\n' if args[-1]=='Fixture Browser' else '','')   # --target-app matches exact names only
        with patch.object(atticus,'app_named',side_effect=lambda w:'Fixture Browser' if w.lower() in ('browser','fixture browser') else None), \
             patch.object(atticus.subprocess,'run',side_effect=native):
            self.assertEqual(atticus.running_app('browser'),'Fixture Browser')   # "fill the form in <its short name>"
            self.assertEqual(atticus.running_app('Fixture Browser'),'Fixture Browser')
            self.assertEqual(atticus.running_app('Elsewhere'),'')

    def test_readiness_failure_after_a_click_keeps_success_without_repeating(self):
        with tempfile.TemporaryDirectory() as scratch:
            def run(args,**kwargs):
                if 'return (id of window' in args[2]: return subprocess.CompletedProcess(args,0,'10\t2','')
                if 'get {name, bounds}' in args[2]: return subprocess.CompletedProcess(args,0,'Fixture, 0, 0, 300, 200','')
                return subprocess.CompletedProcess(args,0,json.dumps({'what':'Go','short':'Go','url':'https://fixture.invalid'}) if '"name"' in args[-1] else 'Clicked 1: Go','')
            with patch.dict(os.environ,{'ATTICUS_FRONT':'Safari','ATTICUS_ASK':scratch}),patch.object(atticus,'browser_adapter',return_value='webkit'),patch.object(atticus,'preview_app',return_value=None),patch.object(atticus,'hands_map',return_value=None),patch.object(atticus.subprocess,'run',side_effect=run) as worker,patch.object(atticus,'page_ready',side_effect=subprocess.TimeoutExpired('fixture',.5)):
                result=atticus.web('click','1')
            self.assertTrue(result.startswith('Clicked 1'));self.assertIn('Read again',result)
            self.assertEqual(sum('"click"' in call.args[0][-1] for call in worker.call_args_list),1)


    def test_form_submission_always_requires_confirmation_even_with_full_access(self):
        with tempfile.TemporaryDirectory() as scratch:
            def worker(args, **kwargs):
                if 'return (id of window' in args[2]: return subprocess.CompletedProcess(args, 0, '10\t2', '')
                if 'get {name, bounds}' in args[2]: return subprocess.CompletedProcess(args, 0, 'Fixture, 0, 0, 300, 200', '')
                return subprocess.CompletedProcess(args, 0, json.dumps({'what': 'Go', 'short': 'Go', 'url': 'https://fixture.invalid', 'submit': True}), '')
            with patch.dict(os.environ, {'ATTICUS_FRONT': 'Safari', 'ATTICUS_ASK': scratch}), patch.object(atticus, 'browser_adapter', return_value='webkit'), patch.object(atticus, 'pref', return_value=False), patch.object(atticus, 'preview_app', return_value=None), patch.object(atticus.subprocess, 'run', side_effect=worker) as run, patch.object(atticus, 'ask_user', return_value='n') as ask:
                self.assertIn('user said no', atticus.web('click', '1'))
            ask.assert_called_once()
            self.assertFalse(any(')("click"' in call.args[0][-1] for call in run.call_args_list))

    def test_shortcut_submit_refusal_does_not_claim_safe_mode_is_on(self):
        with tempfile.TemporaryDirectory() as scratch:
            def worker(args, **kwargs):
                if 'return (id of window' in args[2]: return subprocess.CompletedProcess(args, 0, '10\t2', '')
                if 'get {name, bounds}' in args[2]: return subprocess.CompletedProcess(args, 0, 'Fixture, 0, 0, 300, 200', '')
                return subprocess.CompletedProcess(args, 0, json.dumps({'what': 'Submit', 'short': 'Submit', 'url': 'https://fixture.invalid', 'submit': True}), '')
            with patch.dict(os.environ, {'ATTICUS_FRONT': 'Safari'}, clear=True), patch.object(atticus, 'DIR', scratch), \
                 patch.object(atticus, 'browser_adapter', return_value='webkit'), patch.object(atticus, 'pref', return_value=False), \
                 patch.object(atticus, 'preview_app', return_value=None), patch.object(atticus.subprocess, 'run', side_effect=worker), \
                 patch.object(atticus, 'ask_user') as ask:
                result = atticus.web('click', '1')
            self.assertIn('needs the user', result)
            self.assertNotIn('Safe mode', result)
            ask.assert_not_called()

    def test_fill_returns_current_field_and_page_state_without_another_model_call(self):
        with tempfile.TemporaryDirectory() as scratch:
            def worker(args, **kwargs):
                if 'return (id of window' in args[2]: return subprocess.CompletedProcess(args, 0, '10\t2', '')
                if 'get {name, bounds}' in args[2]: return subprocess.CompletedProcess(args, 0, 'Fixture, 0, 0, 300, 200', '')
                expression = args[-1]
                output = '{"value":"Current answer"}' if ')("state"' in expression else 'Filled 1' if ')("fill"' in expression else 'Changed page'
                return subprocess.CompletedProcess(args, 0, output, '')
            with patch.dict(os.environ, {'ATTICUS_FRONT': 'Safari', 'ATTICUS_ASK': scratch}), patch.object(atticus, 'browser_adapter', return_value='webkit'), patch.object(atticus, 'preview_app', return_value=None), patch.object(atticus.subprocess, 'run', side_effect=worker), patch.object(atticus, 'page_ready', return_value=True):
                result = atticus.web('fill', '1', 'Answer')
        self.assertIn('Current answer', result)
        self.assertIn('Changed state:', result)
