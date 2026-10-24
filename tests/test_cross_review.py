"""Offline cross-review regressions; Swift snippets use no windows or real apps."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def swift_check(test, code):
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / 'check.swift'
        source.write_text('import Foundation\n' + code)
        result = subprocess.run(['swift', str(source)], capture_output=True, text=True,
                                env={**os.environ, 'ATTICUS_DIR': folder}, timeout=60)
        test.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class CrossReviewTests(unittest.TestCase):
    def test_pause_blocks_shared_agent_start_before_any_side_effect(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source[source.index('    func accept(_ id:String'):source.index('        row["status"]', source.index('    func accept(_ id:String'))]
        swift_check(self, 'enum Prefs { static func bool(_ key:String)->Bool { true } }\n'
                    + 'final class Fixture { var rows:[String:[String:Any]] = ["late":["status":"offered"]]; var started=false\n'
                    + start + '        started=true\n    }\n}\n'
                    + 'let f=Fixture(); f.accept("late"); precondition(!f.started)\n')

    def test_start_guess_counts_agents_waiting_on_the_user_like_the_supervisor(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source.index('        let full = rows.values')
        guess = source[start:source.index('rows[id] = row', start) + len('rows[id] = row')]
        swift_check(self, 'var rows:[String:[String:Any]] = ["a":["status":"running"],"b":["status":"running"],"c":["status":"needs-you"],"new":["status":"offered"]]\n'
                    + 'let id="new"; var row=rows[id]!\n' + guess + '\nprecondition(rows["new"]?["status"] as? String == "queued")\n')

    def test_an_agent_question_sounds_once_per_new_question(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source.index('            let question = { (r:[String:Any]?)')
        check = source[start:source.index('\n', source.index('let asks =', start))]
        swift_check(self, 'func asks(_ kind:String, _ old:[String:Any]?, _ row:[String:Any]) -> Bool { let id="a"; let rows:[String:[String:Any]] = old.map { ["a":$0] } ?? [:]\n'
                    + check + '\n return asks }\n'
                    + 'let q:[String:Any] = ["status":"needs-you","question":["_a":"1"]]\n'
                    + 'precondition(asks("state", ["status":"running"], q))\n'
                    + 'precondition(!asks("state", q, q) && !asks("list", ["status":"running"], q))\n'
                    + 'precondition(asks("state", q, ["status":"needs-you","question":["_a":"2"]]))\n'
                    + 'precondition(!asks("state", ["status":"running"], ["status":"needs-you"]))\n')

    def test_speculative_launch_failure_keeps_listening_until_confirmed(self):
        source = (ROOT / 'Atticus.swift').read_text()
        failure = source[source.index('        guard let w = warm ?? spawn()'):source.index('        warm = nil; proc = w.p')]
        swift_check(self, 'final class Fixture { var warm:Int?, busy=true, pinned=false, ahead="draft", calls=0\n'
                    + 'func spawn()->Int? { nil }; func js(_ s:String) { calls+=1 }; func show() {}; func telemetry(_ a:[String]) {}\n'
                    + 'func run(_ speculative:Bool) { let point:[String:Any]?=nil\n' + failure + ' _=w\n}\n}\n'
                    + 'let f=Fixture(); f.run(true); precondition(f.ahead.isEmpty && !f.busy && !f.pinned && f.calls==0)\n'
                    + 'f.run(false); precondition(f.pinned && f.calls==1)\n')

    def test_failed_resume_and_saving_changes_do_not_apply_success_effects(self):
        source = (ROOT / 'Atticus.swift').read_text()
        resume = source[source.index('            if b["resume"] != nil'):source.index('            if b["kofi"]')]
        saving = source[source.index('        if k == "meetingSave", v as? Bool == false'):source.index('            let alert = NSAlert(); alert.messageText = "Keep your saved meetings?"')]
        swift_check(self, 'enum Prefs { static func bool(_ k:String)->Bool { true }; static func set(_ k:String,_ v:Bool)->Bool { false } }\n'
                    + 'struct Meeting { func savingChanged(_ on:Bool) { fatalError("archive changed") } }; let meeting=Meeting()\n'
                    + 'final class Settings { var notices=0; func apply(_ k:String,_ v:Bool) {}; func push() {}; func send(_ c:String,_ v:[String:String]) { notices+=1 }\n'
                    + 'func saving() { let k="meetingSave", v:Any=false\n' + saving
                    + ' fatalError("saving side effect ran")\n}\n}\n}\n'
                    + 'enum Atticus { static let settings=Settings() }\n'
                    + 'func js(_ c:String,_ v:Bool) { fatalError("resume success shown") }; func hide(after:Double) { fatalError() }\n'
                    + 'let b:[String:Bool]=["resume":true]\n' + resume
                    + 'Atticus.settings.saving(); precondition(Atticus.settings.notices==1)\n')

    def test_out_of_order_model_responses_are_ignored(self):
        source = (ROOT / 'ui/settings.html').read_text()
        method = source[source.index('    models(result)'):source.index('    meetings(result)')].rstrip().rstrip(',')
        esc = source[source.index('  const esc = '):].split('\n', 1)[0]
        script = """const assert=require('assert');
""" + esc + """
const P={apiBase:'b',apiKey:'key',apiModel:''}, nodes={srvnote:{},apimodels:{},apiModel:{}};
const $=id=>nodes[id], document={activeElement:null}, set=(k,v)=>P[k]=v;
const st={""" + method + """};
st.models({base:'b',key:'key',list:['b-model']});
const before=JSON.stringify(nodes);
st.models({base:'a',key:'key',list:['a-model']});
st.models({base:'b',key:'old',list:['old-model']});
assert.equal(P.apiModel,'b-model'); assert.equal(JSON.stringify(nodes),before);
"""
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_broken_pipe_preserves_supervisor_identity_for_restart(self):
        source = (ROOT / 'Atticus.swift').read_text()
        methods = source[source.index('    func send(_ data:[String:Any])'):source.index('    func prepare(_ brief:')]
        swift_check(self, """import Darwin
func py(_ args:[String])->Process { let p=Process(); p.executableURL=URL(fileURLWithPath:"/bin/cat"); return p }
final class Fixture {
 var process:Process?, input:FileHandle?, output:Pipe?, buffer=Data(), lastBox:NSDictionary?, restarts=0
 func receive(_ event:[String:Any]) {}
""" + methods + """
}
let f=Fixture(); f.start(); let first=f.process!
let broken=Pipe(); fcntl(broken.fileHandleForWriting.fileDescriptor,F_SETNOSIGPIPE,1)
try! broken.fileHandleForReading.close(); f.input=broken.fileHandleForWriting
f.send(["action":"list"])
precondition(f.process === first,"write failure stole termination handler identity")
let deadline=Date().addingTimeInterval(8)
while Date()<deadline, f.process==nil || f.process === first { RunLoop.main.run(until:Date().addingTimeInterval(0.05)) }
precondition(f.process != nil && f.process !== first && f.process!.isRunning,"supervisor did not restart")
f.process?.terminate()
""")

    def test_import_actions_only_offer_automation_for_actual_denials(self):
        source = (ROOT / 'ui/settings.html').read_text()
        method = source[source.index('    profileImport(result)'):source.index('    motion(on)')].rstrip().rstrip(',')
        script = """const assert=require('assert');
const nodes={profileImport:{},profileStatus:{textContent:'',children:[],append(v){this.children.push(v)}}};
const $=id=>nodes[id], document={createElement:()=>({})}, post=()=>{};
const st={""" + method + """};
st.profileImport({errors:['contacts','mail'],errorReasons:{contacts:'read',mail:'automation'},counts:{}});
assert.equal(nodes.profileStatus.children[1].textContent,'Allow Mail in Automation');
assert.ok(nodes.profileStatus.children[0].includes('Try importing again'));
nodes.profileStatus.children=[];
st.profileImport({errors:['mail'],errorReasons:{mail:'read'},counts:{contacts:3}});
assert.ok(nodes.profileStatus.children.every(c=>typeof c==='string'));
"""
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
