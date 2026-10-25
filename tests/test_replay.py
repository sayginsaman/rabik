"""Replay actions use scratch storage and fake app workers, never paid calls or personal apps."""
import shlex
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import subprocess
import threading
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.apps, brain.ask, brain.cli, brain.clients, brain.hands, brain.instant, brain.interaction, brain.macos, brain.memory
import brain.paths, brain.protocol, brain.screen, brain.situation, brain.skills, brain.storage, brain.telemetry, brain.tips
import brain.toolhelp, brain.web
from tests import scratch_dir


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.root=scratch_dir(self)
        for p in [patch.object(brain.skills,'SKILLS',str(self.root/'skills.json')),
                  patch.object(brain.paths,'RECENT',str(self.root/'recent.jsonl')),
                  patch.object(brain.paths,'WORKED',str(self.root/'worked.json')),patch.object(brain.memory,'ME_FILE',str(self.root/'me.json')),
                  patch.dict(os.environ,{'RABIK_ASK':str(self.root),'RABIK_FRONT':'Other Fixture','RABIK_FOCUS_GUARD':'1'},clear=True)]:
            p.start();self.addCleanup(p.stop)
        self.commands=['open -a Fixture','peekaboo menu click --app "com.rabik.fixture" --path "Fixture > Start meeting" --no-remote',
                       'osascript -e \'tell application "System Events" to get name of every window of process "Fixture"\'']

    def test_legacy_three_steps_upgrade_and_replay_native_actions_without_ai_or_reads(self):
        (self.root/'skills.json').write_text(json.dumps({'make a fixture meeting':{'cmds':self.commands,'reply':'Started.','mine':True}}))
        with patch.object(brain.web,'show',return_value='opened Fixture in the background') as show,patch.object(brain.hands,'hands',return_value=('Clicked',True)) as hands,patch.object(subprocess,'run') as shell,patch.object(brain.clients,'start_claude') as ai:
            self.assertEqual(brain.instant.fast('Please start a new fixture meeting'),'Started.')
        show.assert_called_once_with('Fixture',True);hands.assert_called_once_with('menu','com.rabik.fixture','Fixture > Start meeting')
        shell.assert_not_called();ai.assert_not_called();self.assertEqual(len(brain.skills.skills()['make a fixture meeting']['cmds']),2)

    def test_internal_partial_request_keys_are_pruned_when_skills_load(self):
        command = brain.paths.SHOW + ' Fixture'
        junk = 'open fixture\nAlready completed: first step\nRemaining words: second step'
        (self.root / 'skills.json').write_text(json.dumps({
            'open fixture': {'cmds': [command], 'reply': 'Opened.', 'mine': True},
            junk: {'cmds': [command], 'reply': 'Opened.', 'mine': True},
        }))
        self.assertEqual(set(brain.skills.skills()), {'open fixture'})
        self.assertEqual(set(json.loads((self.root / 'skills.json').read_text())), {'open fixture'})

    def test_new_shortcuts_drop_reads_and_keep_the_target_when_front_app_changes(self):
        with patch.object(brain.macos,'cached_hands',return_value=None): self.assertTrue(brain.skills.learn('make a fixture meeting',self.commands,'Started.'))
        commands=brain.skills.skills()['make a fixture meeting']['cmds']
        self.assertEqual(commands,[brain.paths.SHOW+' --bg Fixture',brain.paths.HANDS+" menu com.rabik.fixture 'Fixture > Start meeting'"])
        self.assertNotIn('Other Fixture',' '.join(commands))
        self.assertIsNone(brain.skills.shortcut_commands('export',['%s click "File > Export"'%brain.paths.HANDS]))

    def test_a_generalized_replay_learns_the_app_it_actually_used(self):
        brain.skills.save_skills({'put fixture alpha left':{'cmds':['open -a "Fixture Alpha"'],'reply':'Done.','mine':True}})
        resolve=lambda name:{'fixture alpha':'Fixture Alpha','fixture beta':'Fixture Beta'}.get(name.lower())
        with patch.object(brain.apps,'app_named',side_effect=resolve),patch.object(brain.web,'show',return_value='opened'),patch.object(brain.tips,'tip'):
            self.assertEqual(brain.instant.fast('when I say layout mode, put fixture beta left'),'Done.')
        command=brain.skills.skills()['layout mode']['cmds'][0]
        self.assertIn('Fixture Beta',command);self.assertNotIn('Fixture Alpha',command)

    def test_explicit_open_remains_foreground_and_mutating_scripts_are_kept(self):
        script='osascript -e \'tell application "Fixture" to set name of window 1 to "Done"\''
        self.assertEqual(brain.skills.shortcut_commands('open Fixture',['open -a Fixture',script]),['open -a Fixture',script])
        self.assertEqual(brain.skills.shortcut_commands('check',['osascript -e \'get "click"\'']),[])
        found=f'{brain.paths.SHOW} --bg "/tmp/Guide.pdf" && ls /tmp'   # a file found by searching: only the open is replayed
        self.assertEqual(brain.skills.shortcut_commands('study guide',['mdfind -name guide 2>/dev/null | head -20; mdfind x | grep -i y',found]),[f'{brain.paths.SHOW} --bg /tmp/Guide.pdf'])
        with patch.object(brain.macos,'cached_hands',return_value=None): self.assertIsNone(brain.skills.learn('study guide',['ls /tmp > /tmp/out',found],'Opened.'))   # a write is not a lookup

    def test_act_then_sleep_then_state_read_learns_the_act_alone(self):
        play,state='osascript -e \'tell application "Fixture" to play\'','osascript -e \'tell application "Fixture" to player state as string\''
        track='osascript -e \'tell application "Fixture" to name of current track\''
        with patch.object(brain.macos,'cached_hands',return_value=None):
            self.assertTrue(brain.skills.learn('unpause fixture',[f'{play} && sleep 1 && {state}'],'Playing again.'))
            self.assertEqual(brain.skills.skills()['unpause fixture']['cmds'],[play])
            self.assertEqual(brain.skills.shortcut_commands('pause fixture',[f'{play.replace("play","pause")} && {track}']),[play.replace('play','pause')])
            self.assertIsNone(brain.skills.shortcut_commands('play fixture',[f'{state} && {play}']))   # a read before the act: replay would act blind
            self.assertIsNone(brain.skills.learn('play fixture',[f'{state} && sleep 1 && {play}'],'Playing.'))
            delete='osascript -e \'tell application "System Events" to tell process "Fixture" to click button "Delete" of window 1\''
            self.assertIsNone(brain.skills.learn('clear fixture',[f'{delete} && sleep 1 && {state}'],'Cleared.'))   # risky acts stay unlearned
        self.assertEqual(set(brain.skills.skills()),{'unpause fixture'})
        both='osascript -e \'tell application "Fixture" to pause\' -e \'tell application "Fixture" to get player state\''
        self.assertEqual(brain.skills.shortcut_commands('pause fixture',[both,state]),[both])   # an act with its own check in one script stays
        framed='osascript -e \'tell application "System Events"\' -e \'tell process "Fixture" to get name of every window\' -e \'end tell\''
        self.assertEqual(brain.skills.shortcut_commands('windows',[framed]),[])

    def test_replay_says_the_outcome_not_how_the_first_run_went(self):
        play='osascript -e \'tell application "Fixture" to play\''
        (self.root/'skills.json').write_text(json.dumps({'unpause fixture':{'cmds':[play],'reply':'Fixture is playing. The first check still showed it paused, but a second check confirmed it.'}}))
        with patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')):
            self.assertEqual(brain.instant.fast('unpause fixture'),'Fixture is playing.')
        for whole in ['Done: focus mode.','Typed "Hi! See you." into Mail.','Opened 10 Hail Pl. Tell me the city.','Playing 1M. It runs in the background.','I typed your reply into the mail box. It isn’t sent yet.','Notes is open. Do not close it.']:
            self.assertEqual(brain.skills.outcome(whole),whole)

    def test_unsupported_peekaboo_falls_back_without_running(self):
        brain.skills.save_skills({'do fixture':{'cmds':['peekaboo click --id 12'],'reply':'Done.','mine':True}})
        with patch.object(subprocess,'run') as run:self.assertIsNone(brain.skills.replay('do fixture'));run.assert_not_called()
        self.assertIsNone(brain.skills.shortcut_commands('do fixture',[self.commands[-1]+' && open -a Fixture']))
        self.assertIsNone(brain.skills.shortcut_commands('do fixture',[shlex.quote(brain.paths.ME)+' ask again']))
        reply,saved=brain.skills.remember_workflow('nested fixture',f'Done. [workflow nested fixture | Use the native app.] [replay python3 {shlex.quote(brain.paths.ME)} ask again]',True,['open Fixture'])
        self.assertTrue(saved);self.assertNotIn('nested fixture',brain.skills.skills())

    def test_native_menu_bypasses_map_capture_but_waits_for_confirmation(self):
        args=('menu','com.rabik.fixture','Fixture > Start meeting')
        worker=unittest.mock.Mock(returncode=0,stdout='Clicked Start meeting\n',stderr='')
        with patch.object(brain.interaction,'wait_commit',return_value=True),patch.object(brain.hands,'hands_call',return_value=worker) as call,patch.object(brain.hands,'hands_map') as mapping:
            self.assertTrue(brain.hands.hands(*args)[1]);call.assert_called_once_with(list(args),timeout=2);mapping.assert_not_called()
        with patch.object(brain.interaction,'wait_commit',return_value=False),patch.object(brain.hands,'hands_call') as call:
            self.assertFalse(brain.hands.hands(*args)[1]);call.assert_not_called()

    def test_guarded_background_open_does_not_poll_or_sleep(self):
        with patch.object(brain.macos,'osa') as osa,patch.object(time,'sleep') as sleep,patch.object(brain.macos,'preview_app'),patch.object(subprocess,'run',return_value=unittest.mock.Mock(returncode=0)):
            brain.web.show('Fixture',bg=True);osa.assert_not_called();sleep.assert_not_called()

    def test_failed_direct_open_falls_back_instead_of_claiming_success(self):
        brain.skills.save_skills({'open fixture':{'cmds':[brain.paths.SHOW+' Fixture'],'reply':'Opened.','mine':True}})
        with patch.object(brain.web,'show',return_value='no app or file called "Fixture"'):
            self.assertIsNone(brain.skills.replay('open fixture'))

    def test_recent_memory_creates_missing_scratch_directory(self):
        missing=self.root/'new';recent=missing/'recent.jsonl'
        with patch.object(brain.paths,'DIR',str(missing)),patch.object(brain.paths,'RECENT',str(recent)):
            brain.memory.remember_turn('Find fixture notes','Found them.');self.assertEqual(brain.memory.recent()[0]['q'],'Find fixture notes')
            self.assertEqual(recent.stat().st_mode&0o777,0o600)
            with patch.object(os,'replace',side_effect=OSError('disk full')):
                with self.assertRaises(OSError): brain.memory.remember_turn('Other ask','Other answer')
            self.assertEqual(brain.memory.recent()[0]['q'],'Find fixture notes')

    def test_first_ai_answer_saves_memory_and_log_in_a_fresh_directory(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        missing=self.root/'fresh';fake_run=unittest.mock.Mock(return_value=('Found them. [unlearn]',0,[]));fake_run.ok=True;fake_run.cmds=[];fake_run.ran=[];fake_run.observed=[]
        with patch.object(brain.paths,'DIR',str(missing)),patch.object(brain.paths,'RECENT',str(missing/'recent.jsonl')),patch.object(brain.paths,'MEMORY',str(missing/'memory.md')),patch.object(threading,'Thread',NoThread),patch('sys.argv',['rabik.py','Find fixture notes']),tests.patches(patch.multiple(brain.telemetry, ping=lambda:None),
                                                                                                                                                                                                                                                                                     patch.multiple(brain.instant, fast=lambda _:None),
                                                                                                                                                                                                                                                                                     patch.multiple(brain.macos, front=lambda:('Fixture','Scratch'), osa=lambda *a:'', screens=lambda:[], describe=lambda *a:'Scratch display', restore_focus=lambda *a:None),
                                                                                                                                                                                                                                                                                     patch.multiple(brain.situation, selection_context=lambda:''),
                                                                                                                                                                                                                                                                                     patch.multiple(brain.screen, screen_for=lambda *a:None, look=lambda:[]),
                                                                                                                                                                                                                                                                                     patch.multiple(brain.ask, run=fake_run),
                                                                                                                                                                                                                                                                                     patch.multiple(brain.interaction, wait_commit=lambda:True),
                                                                                                                                                                                                                                                                                     patch.multiple(brain.protocol, say=lambda *a:None),
                                                                                                                                                                                                                                                                                     patch.multiple(brain.tips, tip=lambda *a:None),
                                                                                                                                                                                                                                                                                     patch.multiple(brain.hands, hands_map=lambda *a:None)):
            brain.cli.main();self.assertEqual(brain.memory.recent()[0]['a'],'Found them.');self.assertTrue((missing/'log.jsonl').exists())
        fake_run.assert_called_once()

    def test_bare_running_check_is_dropped_and_a_new_shortcut_or_workflow_shows_the_learned_pill(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        quit,check='osascript -e \'tell application "Fixture" to quit\'','osascript -e \'application "Fixture" is running\''
        self.assertEqual(brain.skills.shortcut_commands('close fixture',[quit,check]),[quit])
        self.assertEqual(brain.skills.shortcut_commands('close fixture',[f'{quit} && sleep 1 && {check.replace("is","is not")}']),[quit])
        self.assertIsNone(brain.skills.shortcut_commands('close fixture',[f'{check} && {quit}']))   # a check before the act still refuses
        guarded='osascript -e \'tell application "Fixture"\' -e \'if player state is playing then pause\' -e \'end tell\''
        self.assertEqual(brain.skills.shortcut_commands('pause fixture',[guarded]),[guarded])
        def ask(task,reply,cmds):
            fake_run=unittest.mock.Mock(return_value=(reply,0,[]));fake_run.ok=True;fake_run.cmds=cmds;fake_run.ran=cmds;fake_run.observed=[]
            tip=unittest.mock.Mock()
            with patch.object(brain.paths,'DIR',str(self.root)),patch.object(brain.paths,'RECENT',str(self.root/'recent.jsonl')),patch.object(brain.paths,'MEMORY',str(self.root/'memory.md')),patch.object(threading,'Thread',NoThread),patch('sys.argv',['rabik.py',task]),tests.patches(patch.multiple(brain.telemetry, ping=lambda:None),
                                                                                                                                                                                                                                                                               patch.multiple(brain.instant, fast=lambda _:None),
                                                                                                                                                                                                                                                                               patch.multiple(brain.macos, front=lambda:('Fixture','Scratch'), osa=lambda *a:'', screens=lambda:[], describe=lambda *a:'Scratch display', restore_focus=lambda *a:None, cached_hands=lambda:None),
                                                                                                                                                                                                                                                                               patch.multiple(brain.situation, selection_context=lambda:''),
                                                                                                                                                                                                                                                                               patch.multiple(brain.screen, screen_for=lambda *a:None, look=lambda:[]),
                                                                                                                                                                                                                                                                               patch.multiple(brain.ask, run=fake_run),
                                                                                                                                                                                                                                                                               patch.multiple(brain.interaction, wait_commit=lambda:True),
                                                                                                                                                                                                                                                                               patch.multiple(brain.protocol, say=lambda *a:None),
                                                                                                                                                                                                                                                                               patch.multiple(brain.tips, tip=tip),
                                                                                                                                                                                                                                                                               patch.multiple(brain.hands, hands_map=lambda *a:None)):
                with patch.object(brain.apps,'app_id',return_value='com.example.fixture'),patch.object(brain.apps,'app_running',return_value=False): brain.cli.main()
            return tip.call_args.args[1]
        self.assertEqual(ask('Close fixture','Fixture is closed.',[quit,check]),'Learned: Say “Close fixture” any time.')
        self.assertEqual(brain.skills.skills()['close fixture']['cmds'],[quit])
        self.assertEqual(brain.memory.recent()[-1]['shortcut']['key'],'close fixture')
        self.assertEqual(ask('Close fixture','Fixture is closed.',[quit,check]),'')   # already known: no pill
        self.assertEqual(ask('Tidy fixture','Tidied. [workflow tidy fixture | Use the View menu.]',[f'{brain.paths.HANDS} see Fixture']),'Learned: Procedure saved for next time.')

    def test_instant_quit_uses_bundle_id_verifies_and_beats_old_skill(self):
        old='osascript -e \'tell application "Fixture Display" to quit\''
        brain.skills.save_skills({'close fixture display':{'cmds':[old],'reply':'Old false success.','mine':True},
                             'end fixture':{'cmds':[old],'reply':'Ended.','mine':True}})
        resolve=lambda name: 'Fixture' if name == 'fixture display' else None
        with patch.object(brain.apps,'app_named',side_effect=resolve),patch.object(brain.apps,'app_id',return_value='com.example.fixture') as app_id, \
             patch.object(brain.apps,'quit_app',return_value=True) as quit_app,patch.object(brain.skills,'replay') as replay:
            self.assertEqual(brain.instant.fast('close fixture display'),'Closed Fixture.')
            app_id.assert_called_once_with('Fixture');quit_app.assert_called_once_with('com.example.fixture');replay.assert_not_called()
            self.assertIn('application id "com.example.fixture"',brain.instant.fast.cmds[0])
            self.assertIsNone(brain.instant.fast('close this tab'))
            self.assertIsNone(brain.instant.fast('close the window'))
        with patch.object(brain.apps,'app_named',side_effect=resolve),patch.object(brain.apps,'app_id',return_value='com.example.fixture'), \
             patch.object(brain.apps,'quit_app',return_value=False):
            self.assertEqual(brain.instant.fast('quit fixture display'),'Fixture is still open.')
            self.assertEqual(brain.instant.fast.cmds,[])
        with patch.object(brain.apps,'app_named',return_value='Fixture'),patch.object(brain.apps,'app_id',return_value='com.example.fixture') as app_id, \
             patch.object(brain.apps,'quit_app',return_value=True) as quit_app,patch.object(subprocess,'run') as shell:
            self.assertEqual(brain.skills.replay('end fixture'),'Ended.')
            app_id.assert_called_once_with('Fixture');quit_app.assert_called_once_with('com.example.fixture');shell.assert_not_called()
        with patch.object(brain.apps,'app_running',side_effect=[True,True,False]),patch.object(brain.macos,'osa') as osa,patch.object(time,'sleep'):
            self.assertTrue(brain.apps.quit_app('com.example.fixture'))
        osa.assert_called_once_with('tell application id "com.example.fixture" to quit',timeout=2)

    def test_user_reported_failure_unlearns_without_saving_the_correction(self):
        command='osascript -e \'tell application "Fixture" to set visible to false\''
        brain.skills.save_skills({'hide fixture':{'cmds':[command],'reply':'Fixture is hidden.','mine':True}})
        worker=unittest.mock.Mock(returncode=0,stdout='fixture became hidden\n',stderr='')
        with patch.object(subprocess,'run',return_value=worker),patch.object(brain.macos,'preview_commands'):
            answer=brain.instant.fast('hide fixture')
        self.assertEqual(answer,'Fixture is hidden.')
        brain.memory.remember_turn('hide fixture',answer,brain.instant.fast.shortcut)

        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        fake_run=unittest.mock.Mock(return_value=('Fixture is hidden now. [unlearn] [workflow hide fixture | Hide it, then check.]',0,[]))
        fake_run.ok=True;fake_run.cmds=fake_run.ran=[command];fake_run.observed=[{'action':command,'error':False,'result':'verified hidden'}]
        say=unittest.mock.Mock()
        with patch.object(threading,'Thread',NoThread),patch('sys.argv',['rabik.py','It is still visible']), \
             tests.patches(patch.multiple(brain.telemetry, ping=lambda:None),
                           patch.multiple(brain.instant, fast=lambda _:None),
                           patch.multiple(brain.macos, front=lambda:('Fixture','Scratch'), osa=lambda *a:'', screens=lambda:[], describe=lambda *a:'Scratch display', restore_focus=lambda *a:None),
                           patch.multiple(brain.situation, selection_context=lambda:''),
                           patch.multiple(brain.screen, screen_for=lambda *a:None, look=lambda:[]),
                           patch.multiple(brain.toolhelp, tool_help=lambda *a,**k:''),
                           patch.multiple(brain.ask, run=fake_run),
                           patch.multiple(brain.interaction, wait_commit=lambda:True),
                           patch.multiple(brain.protocol, say=say),
                           patch.multiple(brain.tips, tip=lambda *a:None),
                           patch.multiple(brain.hands, hands_map=lambda *a:None)):
            brain.cli.main()
        self.assertEqual(say.call_args.args[1],'Fixture is hidden now.')   # no control tag shows, and the redo saves nothing
        self.assertEqual(brain.skills.workflows(),{})
        prompt=fake_run.call_args.args[0]
        self.assertIn('Previous learned shortcut',prompt)
        self.assertIn('hide fixture',prompt)
        self.assertIn('fixture became hidden',prompt)
        self.assertEqual(fake_run.call_args.kwargs['request'],'It is still visible')
        self.assertNotIn('hide fixture',brain.skills.skills())

    def test_unrelated_ask_after_replay_keeps_the_shortcut(self):
        command='osascript -e \'tell application "Fixture" to set visible to false\''
        brain.skills.save_skills({'hide fixture':{'cmds':[command],'reply':'Fixture is hidden.','mine':True}})
        worker=unittest.mock.Mock(returncode=0,stdout='fixture became hidden\n',stderr='')
        with patch.object(subprocess,'run',return_value=worker),patch.object(brain.macos,'preview_commands'):
            answer=brain.instant.fast('hide fixture')
        brain.memory.remember_turn('hide fixture',answer,brain.instant.fast.shortcut)

        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        fake_run=unittest.mock.Mock(return_value=('The unrelated answer.',0,[]))
        fake_run.ok=True;fake_run.cmds=fake_run.ran=[];fake_run.observed=[]
        with patch.object(threading,'Thread',NoThread),patch('sys.argv',['rabik.py','Explain an unrelated topic']), \
             tests.patches(patch.multiple(brain.telemetry, ping=lambda:None),
                           patch.multiple(brain.instant, fast=lambda _:None),
                           patch.multiple(brain.macos, front=lambda:('Fixture','Scratch'), osa=lambda *a:'', screens=lambda:[], describe=lambda *a:'Scratch display', restore_focus=lambda *a:None),
                           patch.multiple(brain.situation, selection_context=lambda:''),
                           patch.multiple(brain.screen, screen_for=lambda *a:None, look=lambda:[]),
                           patch.multiple(brain.toolhelp, tool_help=lambda *a,**k:''),
                           patch.multiple(brain.ask, run=fake_run),
                           patch.multiple(brain.interaction, wait_commit=lambda:True),
                           patch.multiple(brain.protocol, say=lambda *a:None),
                           patch.multiple(brain.tips, tip=lambda *a:None),
                           patch.multiple(brain.hands, hands_map=lambda *a:None)):
            brain.cli.main()
        self.assertIn('Previous learned shortcut',fake_run.call_args.args[0])
        self.assertIn('hide fixture',brain.skills.skills())

    def test_stray_unlearn_control_is_never_shown(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        fake_run=unittest.mock.Mock(return_value=('Done. [unlearn]',0,[]))
        fake_run.ok=True;fake_run.cmds=fake_run.ran=[];fake_run.observed=[]
        say=unittest.mock.Mock()
        with patch.object(threading,'Thread',NoThread),patch('sys.argv',['rabik.py','Do the fixture task']), \
             tests.patches(patch.multiple(brain.telemetry, ping=lambda:None),
                           patch.multiple(brain.instant, fast=lambda _:None),
                           patch.multiple(brain.macos, front=lambda:('Fixture','Scratch'), osa=lambda *a:'', screens=lambda:[], describe=lambda *a:'Scratch display', restore_focus=lambda *a:None),
                           patch.multiple(brain.situation, selection_context=lambda:''),
                           patch.multiple(brain.screen, screen_for=lambda *a:None, look=lambda:[]),
                           patch.multiple(brain.toolhelp, tool_help=lambda *a,**k:''),
                           patch.multiple(brain.ask, run=fake_run),
                           patch.multiple(brain.interaction, wait_commit=lambda:True),
                           patch.multiple(brain.protocol, say=say),
                           patch.multiple(brain.tips, tip=lambda *a:None),
                           patch.multiple(brain.hands, hands_map=lambda *a:None)):
            brain.cli.main()
        self.assertEqual(say.call_args.args[1],'Done.')
        self.assertEqual(brain.memory.recent()[-1]['a'],'Done.')

    def test_failed_replay_is_redone_and_successful_recovery_replaces_it(self):
        quit='osascript -e \'tell application "Fixture" to quit\''
        brain.skills.save_skills({'bye fixture':{'cmds':[quit],'reply':'Fixture is closed.','mine':True}})
        with tests.patches(patch.multiple(brain.apps, app_id=lambda *a:'com.example.fixture', app_named=lambda *a:None),
                           patch.multiple(brain.macos, osa=lambda *a,**k:'')),patch.object(brain.apps,'app_running',side_effect=[True,False]),patch.object(time,'sleep'),patch.object(subprocess,'run') as shell:
            self.assertEqual(brain.instant.fast('bye fixture'),'Fixture is closed.')   # verified: the same instant reply
            self.assertIsNone(brain.instant.fast.failed);shell.assert_not_called()
        with patch.object(brain.macos,'wants_focus',return_value=True),tests.patches(patch.multiple(brain.apps, app_id=lambda *a:'com.example.fixture', app_named=lambda *a:None),
                                                                               patch.multiple(brain.macos, osa=lambda *a,**k:'')),patch.object(time,'sleep'),patch.object(brain.macos,'preview_commands'), \
             patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')):
            brain.skills.save_skills({**brain.skills.skills(),'show fixture':{'cmds':['open -a Fixture'],'reply':'Opened.','mine':True}})
            with patch.object(brain.apps,'app_running',return_value=False): self.assertIsNone(brain.skills.replay('show fixture'))
            self.assertEqual(brain.skills.replay.ran[-1],'Fixture => not running')
            with patch.object(brain.apps,'app_running',return_value=True): self.assertEqual(brain.skills.replay('show fixture'),'Opened.')

        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        replacement=brain.paths.HANDS+" menu com.example.fixture 'Fixture > Quit'"
        fake_run=unittest.mock.Mock(return_value=('Fixture is closed now; the shortcut had not quit it. [unlearn]',0,[]))
        fake_run.ok=True;fake_run.cmds=fake_run.ran=[replacement]
        fake_run.observed=[{'action':replacement,'error':False,'result':'Fixture closed'}]
        say,tip=unittest.mock.Mock(),unittest.mock.Mock()
        with patch.object(threading,'Thread',NoThread),patch('sys.argv',['rabik.py','bye fixture']),patch.object(brain.apps,'app_running',return_value=True),patch.object(time,'sleep'), \
             tests.patches(patch.multiple(brain.apps, app_id=lambda *a:'com.example.fixture', app_named=lambda *a:None),
                           patch.multiple(brain.macos, osa=lambda *a,**k:'', front=lambda:('Fixture','Scratch'), screens=lambda:[], describe=lambda *a:'Scratch display', restore_focus=lambda *a:None, cached_hands=lambda:None),
                           patch.multiple(brain.telemetry, ping=lambda:None, report=lambda *a:None),
                           patch.multiple(brain.situation, selection_context=lambda:''),
                           patch.multiple(brain.screen, screen_for=lambda *a:None, look=lambda:[]),
                           patch.multiple(brain.toolhelp, tool_help=lambda *a,**k:''),
                           patch.multiple(brain.ask, run=fake_run),
                           patch.multiple(brain.interaction, wait_commit=lambda:True),
                           patch.multiple(brain.protocol, say=say),
                           patch.multiple(brain.tips, tip=tip),
                           patch.multiple(brain.hands, hands_map=lambda *a:None)):
            brain.cli.main()
        said=[c.args for c in say.call_args_list]
        self.assertIn(('▸','The shortcut did not work. Redoing it'),said)
        self.assertNotIn('Fixture is closed.',[s for _,s in said])   # never the learned success line
        self.assertEqual(said[-1][1],'Fixture is closed now; the shortcut had not quit it.')
        prompt=fake_run.call_args.args[0]
        self.assertIn('still open',prompt);self.assertIn('failed (see its output): redo the request',prompt)
        self.assertEqual(brain.skills.skills()['bye fixture']['cmds'],[replacement])
        self.assertEqual(tip.call_args.args[1],'Learned: Say “bye fixture” any time.')

    def test_a_quit_that_is_still_running_is_not_learned(self):
        command='osascript -e \'tell application id "com.example.fixture" to quit\''
        with patch.object(brain.macos,'cached_hands',return_value=None),patch.object(brain.apps,'app_running',return_value=True):
            self.assertIsNone(brain.skills.learn('close fixture',[command],'Fixture is closed.'))
        with patch.object(brain.skills,'shortcut_commands',return_value=['osascript -e "']):
            self.assertIsNone(brain.skills.learn('malformed fixture',[command],'Done.'))
        self.assertNotIn('close fixture',brain.skills.skills())

    def test_reference_ask_receives_recent_target_and_agent_history(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        url='https://fixture.example/posts/42'
        agent=self.root/'agents'/('a'*32);agent.mkdir(parents=True)
        brain.storage.private_json(str(agent/'context.json'),{'id':'a'*32,'status':'done','created':time.time(),
                                                       'brief':'Find a useful post','links':[url]})
        (self.root/'worked.json').write_text(json.dumps({'app':'Reader Fixture','window':'Earlier post'}))
        fake_run=unittest.mock.Mock(return_value=('Opened the earlier post.',0,[]));fake_run.ok=True;fake_run.cmds=[];fake_run.ran=[];fake_run.observed=[]
        with patch.object(brain.paths,'RECENT',str(self.root/'recent.jsonl')),patch.object(brain.paths,'MEMORY',str(self.root/'memory.md')):
            brain.memory.remember_turn('Find a useful post','Opened '+url)
            with patch.object(threading,'Thread',NoThread),patch('sys.argv',['rabik.py','Open that post you opened']),tests.patches(patch.multiple(brain.telemetry, ping=lambda:None),
                                                                                                                                          patch.multiple(brain.instant, fast=lambda _:None),
                                                                                                                                          patch.multiple(brain.macos, front=lambda:('Fixture','Scratch'), osa=lambda *a:'', screens=lambda:[], describe=lambda *a:'Scratch display', restore_focus=lambda *a:None),
                                                                                                                                          patch.multiple(brain.situation, selection_context=lambda:''),
                                                                                                                                          patch.multiple(brain.screen, screen_for=lambda *a:None, look=lambda:[]),
                                                                                                                                          patch.multiple(brain.ask, run=fake_run),
                                                                                                                                          patch.multiple(brain.interaction, wait_commit=lambda:True),
                                                                                                                                          patch.multiple(brain.protocol, say=lambda *a:None),
                                                                                                                                          patch.multiple(brain.tips, tip=lambda *a:None),
                                                                                                                                          patch.multiple(brain.hands, hands_map=lambda *a:None)):
                brain.cli.main()
        prompt=fake_run.call_args.args[0]
        self.assertIn('Earlier:\nQ: Find a useful post\nA: Opened '+url,prompt)
        self.assertIn('Last task worked in: Reader Fixture "Earlier post"',prompt)
        self.assertIn('Background tasks',prompt);self.assertIn('a'*32,prompt)
        self.assertEqual(fake_run.call_args.kwargs['request'],'Open that post you opened')
