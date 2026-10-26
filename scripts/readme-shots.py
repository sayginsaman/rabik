#!/usr/bin/env python3
"""README screenshots (docs/screens/*.png): Rabik's real pages with demo data, drawn offscreen by scripts/shot.swift. No Mac,
account or user data is read; run it after a UI change: python3 scripts/readme-shots.py"""
import base64
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'screens'
ICON = 'data:image/png;base64,' + base64.b64encode((ROOT / 'docs' / 'icon.png').read_bytes()).decode()
WAIT = 'await new Promise(r=>setTimeout(r,1800));'
DAY = 1792929600   # Oct 24, 2026

SCENES = {
    'answer': ('ui/ui.html', 'c,h', 440, 700, '#card', 'box', 1, f"""
ui.listen(); ui.words('What did we decide about pricing last week, and what do I owe Sam?'); ui.think();
ui.line('▸ Reading your meetings'); ui.line('▸ Checking About you'); {WAIT}
ui.line('✓ In **Pricing review** (Thu) you agreed to raise Pro to **$24/month** from May 1 and keep the yearly plan at $199.\\u2028\\u2028You owe Sam two things:\\u2028\\u2028- The updated pricing deck by **Friday**\\u2028- A note to existing customers before the change');
ui.line('⌖ ' + JSON.stringify([{{kind:'meeting',id:'m1',label:'Pricing review · Oct 22'}},{{kind:'person',id:'sam',label:'Sam Lee'}},{{kind:'fact',id:'f',label:'People · Sam is head of sales'}}]));"""),
    'recap': ('ui/ui.html', 'c,h', 440, 1400, '#card', 'box', 1, """
const open=document.createElement('style');open.textContent='.agent-card.recap-card .a,#thread{max-height:none!important;overflow:visible!important}';document.head.append(open);
ui.recap({day:'2026-10-24',headline:'Pricing settled, beta tests green, two follow-ups',source:'ai',
 highlights:['Agreed Pro goes to $24/month from May 1','An agent finished the beta test run: 214 passing'],
 decisions:['Yearly plan stays at $199'],
 actions:[{text:'Send Sam the updated pricing deck',source:'Pricing review',from:'meeting:m1',due:'2026-10-25',key:'a',added:''},{text:'Email existing customers about the change',source:'Pricing review',from:'meeting:m1',due:'',key:'b',added:''},{text:'Review the offsite agenda',source:'Agent: Offsite plan',from:'agent:x',due:'',key:'c',added:'x'}],
 goals:[{goal:'Ship the beta by Friday',note:'All 214 tests pass; only the release notes are left.'}],
 focus:['Pricing v3 · Figma · 1 h 10 min','App.swift · Xcode · 48 min'], tomorrow:['09:30 Design sync','14:00 Call with Priya']});
document.querySelectorAll('.todo')[0]?.click(); document.getElementById('thread').scrollTop=0;"""),
    'meeting': ('ui/meeting.html', 'meeting', 340, 640, '', 'meeting', 1, """
meeting.width(340); meeting.listen(); meeting.capturing(); meeting.clock(754); meeting.saving(true);
meeting.question({id:5,text:'What did we charge for Pro last year?',seconds:748,speaker:'Sam Lee'});
meeting.answerChunk({id:5,text:'Pro was $19/month last year; yearly was $179 (from your notes).'});
meeting.answer({id:5,kind:'answer',lines:['Pro was $19/month last year; yearly was $179 (from your notes).']});"""),
    'transcript': ('ui/meeting.html', 'meeting', 340, 520, '', 'meeting', 1, """
meeting.width(340); meeting.listen(); meeting.capturing(); meeting.clock(754); meeting.saving(true);
const L=(id,t,s,extra={})=>meeting.line({id,text:t,seconds:s,...extra});
L(1,'Thanks everyone for joining, let us look at pricing.',702,{name:'Sam Lee'});
L(2,'I think the Pro plan should move to twenty-four dollars.',716);
L(3,'Agreed, and keep yearly at one ninety-nine.',724,{mic:true});
L(4,'Bütçe tarafında sorun yok, mayısta başlayabiliriz.',738);
L(6,'Then I will send the updated deck by Friday.',751,{name:'Sam Lee'});
meeting.speakers({'2':'Priya Shah','4':'Deniz Kaya'}); meeting.translated({id:4,text:'The budget is fine; we can start in May.'});
document.querySelector('#tabs [data-tab=transcript]').click();"""),
    'people': ('ui/settings.html', 'st', 780, 560, '', 'window', 0, f"""
st.load({{prefs:{{hotkeyLabel:'⌃⌥Space',meeting:true}},icon:'{ICON}',version:'1.0.0'}}); st.tab('people');
st.people({{people:{json.dumps([
    {'id': 'sam@acme.com', 'name': 'Sam Lee', 'email': 'sam@acme.com', 'last': DAY - 2 * 86400 + 50400, 'meetings': [{'id': 'm2', 'title': 'Pricing review', 'started': DAY - 2 * 86400 + 50400}, {'id': 'm1', 'title': 'Q4 planning', 'started': DAY - 9 * 86400 + 36000}], 'facts': ['Sam Lee: head of sales at Acme', 'Prefers short decks']},
    {'id': 'priya@acme.com', 'name': 'Priya Shah', 'email': 'priya@acme.com', 'last': DAY - 2 * 86400, 'meetings': [], 'facts': []}])}}});
document.querySelector('#peoplelist .meetingrow').click();"""),
    'activity': ('ui/settings.html', 'st', 780, 560, '', 'window', 0, f"""
st.load({{prefs:{{hotkeyLabel:'⌃⌥Space',activity:true,activityExclude:[{{id:'com.apple.MobileSMS',name:'Messages'}}],learnMe:true}},icon:'{ICON}',version:'1.0.0'}}); st.tab('memory');
const use={{asks:0,usd:0,secs:0}};
st.state({{today:use,week:use,all:use,rules:['Keep answers to three lines','Use metric units'],skills:[{{say:'focus mode',reply:'Closed Slack, opened Things'}}],
  me:{{facts:[{{id:'f1',category:'basics',kind:'name',value:'Alex',source:'you',date:''}},{{id:'f2',category:'school_work',kind:'company',value:'Acme',source:'you',date:''}},
             {{id:'f3',category:'people',kind:'Sam Lee',value:'head of sales',source:'learned',date:''}}]}},plan:{{ok:true,text:'Ready'}}}});
const h=[...document.querySelectorAll('#memory h3')].find(e=>e.textContent==='Rules');document.querySelector('main').scrollTop=h.getBoundingClientRect().top+document.querySelector('main').scrollTop-40;"""),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tool = Path(tmp) / 'shot'
        subprocess.run(['xcrun', 'swiftc', '-O', str(ROOT / 'scripts' / 'shot.swift'), '-o', str(tool)], check=True)
        for name, (page, handlers, w, h, sel, panel, dark, script) in SCENES.items():
            subprocess.run([str(tool), str(ROOT / page), handlers, str(w), str(h), sel, panel, str(dark), script, str(OUT / f'{name}.png')], check=True)
            print('wrote', OUT / f'{name}.png')


if __name__ == '__main__':
    main()
