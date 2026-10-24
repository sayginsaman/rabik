"""ui/ui.html in a real WKWebView that is never put in a window: a streamed answer, the Learned pill and an agent's done card."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_shelf_page import HARNESS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
const a = () => document.querySelector('#thread .turn:last-child .a'), out = {};
ui.listen(); ui.words('what is it'); ui.think();
ui.line('… See [1] and a[0]\u2028- [ ] a task and'); out.brackets = [...a().querySelectorAll('p, li')].map(e => e.textContent.trim());
ui.line('… '); ui.line('… It [the link](https://x.co'); out.open = a().textContent.trim();
ui.line('… It [the link](https://x.co) and'); out.link = [a().querySelector('a')?.textContent, a().textContent.trim()];
ui.line('✓ It [the link](https://x.co) and more.'); out.final = [a().textContent, a().classList.contains('streaming')];
ui.listen(); ui.words('area'); ui.think(); out.math = [];
for (const s of ['the area is $', 'the area is $\\pi r', 'the area is $\\pi r^2', 'the area is $\\pi r^2$ cm', 'the area is $\\pi r^2$ cm and costs $5 today']) { ui.line('… ' + s); out.math.push(a().textContent.trim()); }
out.math.push(!!a().querySelector('math'));
ui.agentDone({id: 'x', title: 'Compare phones', status: 'done', result: 'Found **three** phones [1].', summary: ''});
const card = document.querySelector('.agent-card');
out.card = [card.querySelector('b').textContent, card.querySelector('.a').textContent.trim(), [...card.querySelectorAll('.agent-actions button')].map(b => b.textContent)];
const later = card.querySelector('.agent-actions button:not(.go)'), settle = () => document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());   // no window: WebKit never advances motion
later.scrollIntoView(); const r = later.getBoundingClientRect(), rest = getComputedStyle(later).backgroundColor;
out.hot = [ui.pointer([r.x + r.width / 2, r.y + r.height / 2], false), later.classList.contains('hot'), card.classList.contains('hot')]; settle(); out.hot.push(rest !== getComputedStyle(later).backgroundColor);
out.off = [ui.pointer([]), document.querySelectorAll('.hot').length];
out.x = [ui.pointer([1, 1], true), document.getElementById('x').classList.contains('hot'), later.classList.contains('hot')]; ui.pointer([]);
ui.agentDone({id:'setup', title:'Set up focus time', summary:'Ready.', learned:'focus time'});
out.agentLearned = [document.querySelector('.agent-card .tip.learned')?.dataset.k, document.querySelector('.agent-card .tip.learned')?.textContent];
ui.agentDone({id:'other', title:'Other task', summary:'Done.'}); out.noStaleLearned = !document.querySelector('.agent-card .tip.learned');
const ack = () => document.querySelector('#thread .turn:last-child .agent-ack span').textContent;
ui.listen(); ui.agentSteered({id: 'b1', title: 'Ebikes', steer: {text: 'under $1500'}}); ui.agentStarted({id: 'c1', title: 'Bike locks', status: 'running'});
out.steerAndNew = ack();
ui.listen(); ui.agentStarted({id: 'c1', title: 'Ebikes', status: 'running'}); ui.agentStarted({id: 'd1', title: 'Helmets', status: 'queued'}); out.two = ack();
ui.listen(); ui.agentStarted({id: 'e1', title: 'Tents', status: 'queued'}); ui.agentStarted({id: 'f1', title: 'Stoves', status: 'running'}); ui.agentStarted({id: 'g1', title: 'Maps', status: 'running'}); out.mix = ack();
ui.dictate(true); ui.learned('Atticus'); const dn = document.getElementById('dn');
out.learned = [dn.textContent, getComputedStyle(dn).display, dn.className];
return out;
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class BoxPageTests(unittest.TestCase):
    def test_box_on_real_webkit(self):
        harness = HARNESS.replace('cfg.userContentController.add(h, name: "agents")', 'cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")')
        harness = harness.replace('?["action"] as? String == "ready"', '?["ready"] != nil')
        self.assertEqual(harness.count('name: "c"') + harness.count('["ready"] != nil'), 2)   # the shelf harness, pointed at the box's bridge
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'ui.html', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(harness)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), SCRIPT], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual([p for p in got['posts'] if isinstance(p, dict) and 'error' in p], [])
        out = got['result']
        self.assertEqual(out['brackets'], ['See [1] and a[0]', '[ ] a task'])   # a bracket that is no link shows at once
        self.assertEqual(out['open'], 'It')   # a link still arriving waits
        self.assertEqual(out['link'], ['the link', 'It the link'])
        self.assertEqual(out['final'], ['It the link and more.', False])
        self.assertEqual(out['card'][:2], ['Compare phones', 'Found three phones [1].'])
        self.assertIn('Later', ' '.join(out['card'][2]))
        self.assertEqual(out['hot'], [True, True, True, True])   # the box never activates: the native pointer tints a card button and asks for the hand
        self.assertEqual(out['off'], [False, 0])   # off the box: arrow, no tint
        self.assertEqual(out['x'], [True, True, False])   # native's × corner lights the ×
        self.assertEqual(out['agentLearned'], ['Learned', 'Say “focus time” any time.'])
        self.assertTrue(out['noStaleLearned'])
        self.assertEqual(out['steerAndNew'], 'Told the Ebikes agent: under $1500. I started an agent on “Bike locks”. I’ll ping you when it’s done.')   # one ask, both parts
        self.assertEqual(out['math'][:3], ['the area is', 'the area is', 'the area is'])   # math still arriving waits, never a raw $
        self.assertNotIn('$', out['math'][3]); self.assertTrue(out['math'][3].startswith('the area is π'))
        self.assertTrue(out['math'][4].endswith('and costs $5'))   # a price shows at once
        self.assertTrue(out['math'][5])
        self.assertEqual(out['two'], 'I started an agent on “Ebikes”. I’ll ping you when it’s done. Queued an agent for “Helmets”. It starts when another one finishes.')   # the queued one is not called started
        self.assertEqual(out['mix'], 'Queued an agent for “Tents”. It starts when another one finishes. I started agents on “Stoves” and “Maps”. I’ll ping you when they’re done.')
        self.assertEqual(out['learned'], ['Learned “Atticus” Undo', 'flex', 'dn tick'])


if __name__ == '__main__':
    unittest.main()
