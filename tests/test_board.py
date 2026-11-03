"""The live board: the model's [board …] lines are checked, streamed to the app as ◫ events while the reply arrives, spoken
line by line, and drawn by ui/board.html (real WebKit, no window)."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
from tests import native_source, prompt_chars
from tests.test_shelf_page import HARNESS
from tests import test_stream
from tests.test_stream import message
import brain.board, brain.prompts

ROOT = Path(__file__).resolve().parents[1]
PLAN = '''[board flow: Acme pazarlama planı]
say Birincisi, kime sattığını netleştir.
item Müşteriyi tanı | kim alıyor, neden, nerede arıyor
say Sonra kazanabileceğin iki kanal seç.
item İki kanal seç | SEO · LinkedIn
- item Ölç ve düzelt | aylık gözden geçirme
note Bütçenin çoğu kazanan kanala
circle 2
[/board]
Sources: https://example.com'''


def events(text, final=True):
    stream = brain.board.BoardStream(emit=False)
    stream.feed(text, final=final)
    return stream


class BoardLineTests(unittest.TestCase):
    def test_each_command_becomes_a_checked_event(self):
        line = brain.board.board_line
        self.assertEqual(line('say  Hello **there**.'), {'op': 'say', 'text': 'Hello there.'})
        self.assertEqual(line('item Know your customer | who, why, where'), {'op': 'item', 'text': 'Know your customer', 'detail': 'who, why, where'})
        self.assertEqual(line('item Just a title'), {'op': 'item', 'text': 'Just a title'})
        self.assertEqual(line('bar Q1 = 40%'), {'op': 'bar', 'text': 'Q1', 'value': 40.0, 'unit': '%'})
        self.assertEqual(line('bar Revenue: 1,250,000 USD'), {'op': 'bar', 'text': 'Revenue', 'value': 1250000.0, 'unit': 'USD'})
        self.assertEqual(line('circle 3'), {'op': 'circle', 'n': 3})
        self.assertEqual(line('part Piston | cylinder | 0, 1, 0 | 1,2,1 | silver'),
                         {'op': 'part', 'text': 'Piston', 'shape': 'cylinder', 'at': [0, 1, 0], 'size': [1, 2, 1], 'color': 'silver', 'rot': [0, 0, 0]})
        self.assertEqual(line('part Shaft | box | 0,0,0 | .2,3,.2 | #336699 | 90,0,0')['rot'], [90, 0, 0])
        for kind in ('note', 'check', 'formula', 'column', 'title'):
            self.assertEqual(line(f'{kind} Some words')['op'], kind)

    def test_anything_unknown_or_out_of_range_is_dropped(self):
        for bad in ('', 'say', 'draw a cat', 'rm -rf ~', '<script>alert(1)</script>', 'circle 0', 'circle 99', 'circle two',
                    'bar Q1 = lots', 'part X | hexagon | 0,0,0 | 1,1,1 | red', 'part X | box | 0,0 | 1,1,1 | red',
                    'part X | box | 0,0,999 | 1,1,1 | red', 'part X | box | 0,0,0 | 0,1,1 | red', 'part X | box | 0,0,0 | 1,1,1 | chartreuse',
                    'part X | box | 0,0,0 | 1,1,1 | red | 0,0,720'):
            self.assertIsNone(brain.board.board_line(bad), bad)
        self.assertEqual(len(brain.board.board_line('say ' + 'w' * 900)['text']), 400)
        self.assertEqual(len(brain.board.board_line('item ' + 'w' * 300)['text']), 80)


class BoardStreamTests(unittest.TestCase):
    def test_a_streamed_reply_sends_each_line_once_in_order(self):
        stream = brain.board.BoardStream(emit=False)
        for i in range(1, len(PLAN) + 1):
            self.assertTrue(stream.feed(PLAN[:i]))
        ops = [e['op'] for e in stream.events]
        self.assertEqual(ops, ['open', 'say', 'item', 'say', 'item', 'item', 'note', 'circle', 'end'])
        self.assertEqual(stream.events[0], {'op': 'open', 'layout': 'flow', 'title': 'Acme pazarlama planı', 'append': False})
        self.assertEqual(stream.spoken, ['Birincisi, kime sattığını netleştir.', 'Sonra kazanabileceğin iki kanal seç.'])
        self.assertEqual(stream.state, 'done')
        stream.feed(PLAN + '\nsay after the end'); self.assertEqual(len(stream.events), 9)   # nothing after [/board]

    def test_a_line_is_sent_only_once_it_is_complete(self):
        stream = brain.board.BoardStream(emit=False)
        stream.feed('[board flow: X]\nsay Hel')
        self.assertEqual([e['op'] for e in stream.events], ['open'])
        stream.feed('[board flow: X]\nsay Hello.\nit')
        self.assertEqual(stream.spoken, ['Hello.'])

    def test_plain_answers_are_not_boards(self):
        for text in ('Paris is the capital of France.', '[draft] Dear Ana', '[replace] new text', '```json\n{}', '[agent {"title": "x"}]'):
            stream = brain.board.BoardStream(emit=False)
            self.assertFalse(stream.feed(text + '\nmore'), text)
            self.assertEqual(stream.events, [])
        self.assertTrue(brain.board.BoardStream(emit=False).feed('[bo'))   # may still become one

    def test_the_opening_line_variants(self):
        self.assertEqual(events('[board Marketing plan]\nsay Hi.').events[0], {'op': 'open', 'layout': 'flow', 'title': 'Marketing plan', 'append': False})
        self.assertEqual(events('[board 3d: V8 engine]\nsay Hi.').events[0]['layout'], '3d')
        self.assertEqual(events('[board mind]\nsay Hi.').events[0], {'op': 'open', 'layout': 'mind', 'title': '', 'append': False})
        self.assertTrue(events('[board+]\nsay More.').events[0]['append'])
        self.assertEqual(events('[board+ compare: Next]\nsay More.').events[0]['layout'], 'compare')
        self.assertEqual([e['op'] for e in events('[board flow: X]\nsay No end tag.').events], ['open', 'say', 'end'])   # the final reply closes it

    def test_limits_keep_a_runaway_reply_small(self):
        stream = events('[board flow: X]\n' + 'say Line.\n' * 60 + 'item Step\n' * 120 + ''.join(f'column C{i}\n' for i in range(9)))
        self.assertEqual(stream.counts['say'], 60); self.assertEqual(len(stream.spoken), 40)
        self.assertEqual(sum(e['op'] == 'item' for e in stream.events), 90)
        self.assertEqual(sum(e['op'] == 'column' for e in stream.events), 4)

    def test_events_go_out_as_lines_with_the_spoken_text_for_the_box(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            brain.board.BoardStream(emit=True).feed(PLAN, final=True)
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith('◫ ') and json.loads(lines[0][2:])['op'] == 'open')
        self.assertIn('… Birincisi, kime sattığını netleştir.', lines)
        self.assertIn('… Birincisi, kime sattığını netleştir. Sonra kazanabileceğin iki kanal seç.', lines)
        self.assertEqual(json.loads(lines[-1][2:]), {'op': 'end'})

    def test_the_final_reply_is_what_was_said(self):
        with patch.object(brain.board, 'board_stream', brain.board.BoardStream(emit=False)):
            self.assertEqual(brain.board.board_reply(PLAN), 'Birincisi, kime sattığını netleştir. Sonra kazanabileceğin iki kanal seç.')
            self.assertEqual(brain.board.board_reply('Just text.'), 'Just text.')
            self.assertEqual(brain.board.board_reply('[board flow: X]\nitem Only marks'), 'It’s on the board.')
        self.assertEqual(brain.board.board_spoken(PLAN), 'Birincisi, kime sattığını netleştir. Sonra kazanabileceğin iki kanal seç.')

    def test_a_column_named_again_is_the_same_column(self):
        stream = events('[board compare: Rent or buy]\ncolumn Renting\nitem A\ncolumn Buying\nitem B\ncolumn renting\nitem C\ncolumn Buying\n'
                        'column Later\ncolumn Other\ncolumn Fifth\ncolumn Sixth')
        self.assertEqual([e['text'] for e in stream.events if e['op'] == 'column'], ['Renting', 'Buying', 'renting', 'Buying', 'Later', 'Other'])

    def test_a_follow_up_sees_the_board(self):
        context = brain.board.board_context({'layout': 'flow', 'title': 'Plan', 'items': ['Know them', 'Pick channels', 7]})
        self.assertIn('flow “Plan”: Know them; Pick channels.', context); self.assertIn('[board+]', context)
        self.assertEqual(brain.board.board_context(None), '')


class BoardAskTests(unittest.TestCase):
    """The fake Claude stream (tests/test_stream.py) with a board reply."""
    setUp, run_stream = test_stream.StreamTests.setUp, test_stream.StreamTests.run_stream

    def test_a_board_reply_streams_its_events_and_spoken_text(self):
        reply, lines, shown = self.run_stream(message(PLAN), PLAN)
        boards = [json.loads(line[2:]) for line in lines if line.startswith('◫ ')]
        self.assertEqual([e['op'] for e in boards], ['open', 'say', 'item', 'say', 'item', 'item', 'note', 'circle', 'end'])
        self.assertEqual(shown[-1], 'Birincisi, kime sattığını netleştir. Sonra kazanabileceğin iki kanal seç.')
        self.assertFalse(any('[board' in s or 'item ' in s for s in shown), 'the box never shows the board’s commands')
        self.assertEqual(reply, PLAN)   # cli.py turns it into the spoken text (board_reply)

    def test_a_board_cut_off_by_a_tool_call_is_dropped(self):
        rows = message('[board flow: X]\nsay Looking.\nitem One\n', ('t1', 'curl -s x')) + [{'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': 'ok'}]}}] + message('Done.')
        _, lines, _ = self.run_stream(rows, 'Done.')
        self.assertIn('◫ {"op": "drop"}', lines)

    def test_nothing_is_drawn_before_the_words_are_confirmed(self):
        commit = Path(self.root.name) / 'commit'
        _, lines, _ = self.run_stream(message(PLAN), PLAN, env={'RABIK_COMMIT': str(commit)})
        self.assertFalse(any(line.startswith('◫ ') for line in lines))


class BoardPromptTests(unittest.TestCase):
    def test_the_format_comes_only_with_asks_that_may_want_it(self):
        for ask in ('What should my marketing plan be?', 'how does a car engine work', 'compare iPhone vs Pixel', 'show me a 3d model of a V8',
                    'şirketim için pazarlama planı nasıl olmalı', 'fotosentezi anlat', 'kiralamak ile satın almanın farkı', 'bana bir diyagram çiz'):
            self.assertIn('[board <layout>', brain.prompts.board_help(ask), ask)
        for ask in ('open Safari', 'play some jazz', 'Safari’yi aç', 'mute the sound'):
            self.assertEqual(brain.prompts.board_help(ask), '', ask)
        self.assertIn('[board+]', brain.prompts.board_help('ok', on_board={'title': 'x'}))   # a follow-up to the board on screen

    def test_the_system_prompt_names_it_and_stays_in_budget(self):
        system = brain.prompts.system_prompt(brain.prompts.ASK_FIRST)
        self.assertIn('--board --help', system)
        self.assertLessEqual(prompt_chars(system), 10050)
        for shape in brain.board.BOARD_SHAPES: self.assertIn(shape, brain.prompts.BOARD_HELP)
        for layout in brain.board.BOARD_LAYOUTS: self.assertIn(layout, brain.prompts.BOARD_HELP)

    def test_help_command(self):
        run = subprocess.run([sys.executable, str(ROOT / 'rabik.py'), '--board', '--help'], capture_output=True, text=True, timeout=30,
                             env={**os.environ, 'RABIK_DIR': tempfile.mkdtemp()})
        self.assertIn('[board <layout>: <short title>]', run.stdout)


PAGE = r'''
const tick = ms => new Promise(r => setTimeout(r, ms)), out = {};
board.open({layout: 'flow', title: 'Plan'});
for (const e of [{op:'item',text:'Before any line'},{op:'say',text:'One.'},{op:'item',text:'Know them',detail:'who and why'},{op:'say',text:'Two.'},
                 {op:'item',text:'Pick two'},{op:'item',text:'Measure'},{op:'circle',n:2},{op:'note',text:'Most money to the winner'},{op:'bogus'}]) board.add(e);
await tick(50);
out.preroll = board.marks().map(m => m.drawn);   // marks before the first line show at once; the rest wait for their line
board.play(1, .3); await tick(450);
out.first = board.marks().map(m => m.drawn);
board.play(2, .4); await tick(2100);   // four marks, at least 0.6 s apart
out.all = board.marks().every(m => m.drawn);
out.arrows = document.querySelectorAll('.conn').length;
out.text = [...document.querySelectorAll('#world tspan')].map(s => s.dataset.full).includes('Know them');   // written letter by letter (no window: no frames)
out.summary = board.summary();
board.open({append: true}); board.add({op:'say',text:'Three.'}); board.add({op:'item',text:'Grow'}); board.flush(); await tick(100);
out.appended = board.marks().length;
board.open({layout: 'compare', title: 'Rent or buy'});
for (const e of [{op:'column',text:'Renting'},{op:'item',text:'A'},{op:'column',text:'Buying'},{op:'item',text:'B'},{op:'column',text:'renting'},{op:'item',text:'C'}]) board.add(e);
board.flush(); await tick(50);
out.compare = board.marks().filter(m => m.kind === 'column').length;
board.open({layout: 'chart', title: 'Revenue'}); [{op:'bar',text:'Q1',value:40},{op:'bar',text:'Q2',value:80,unit:'k'}].forEach(board.add); board.flush(); await tick(100);
out.chart = [board.marks().length, document.querySelectorAll('.conn').length, document.getElementById('title').textContent];
board.open({layout: '3d', title: 'Engine'}); board.add({op:'say',text:'Parts.'});
board.add({op:'part',text:'Piston',shape:'cylinder',at:[0,0,0],size:[1,1,1],color:'silver',rot:[0,0,0]}); board.add({op:'item',text:'ignored in 3d'});
board.play(1, .2); await tick(300);
out.three = [board.summary(), document.getElementById('three').classList.contains('on'), getComputedStyle(document.getElementById('ink')).display];
board.end(); await tick(50);
out.hint = document.getElementById('hint').classList.contains('on');
document.getElementById('save').click(); document.getElementById('close').click();
return out;
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class BoardPageTests(unittest.TestCase):
    def test_board_on_real_webkit(self):
        harness = HARNESS.replace('name: "agents"', 'name: "board"').replace('?["action"] as? String == "ready"', '?["do"] as? String == "ready"')
        harness = harness.replace('width: 260, height: 400', 'width: 780, height: 520')
        with tempfile.TemporaryDirectory() as tmp:
            src, binary = Path(tmp) / 'page.swift', Path(tmp) / 'page'
            src.write_text(harness)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(ROOT / 'ui/board.html'), PAGE], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual([p for p in got['posts'] if isinstance(p, dict) and 'error' in p], [])
        out = got['result']
        self.assertEqual(out['preroll'], [True, False, False, False, False, False])
        self.assertEqual(out['first'], [True, True, False, False, False, False])
        self.assertTrue(out['all']); self.assertTrue(out['text'])
        self.assertEqual(out['arrows'], 3)   # flow: an arrow between each pair of cards
        self.assertEqual(out['summary'], {'layout': 'flow', 'title': 'Plan', 'items': ['Before any line', 'Know them', 'Pick two', 'Measure']})
        self.assertEqual(out['appended'], 7)   # [board+] keeps what was drawn
        self.assertEqual(out['compare'], 2)   # "column renting" again is the first column, not a third
        self.assertEqual(out['chart'], [2, 1, 'Revenue'])   # two bars and their axis
        self.assertEqual(out['three'][0], {'layout': '3d', 'title': 'Engine', 'items': ['Piston']})
        self.assertTrue(out['three'][1]); self.assertEqual(out['three'][2], 'none')
        self.assertTrue(out['hint'])
        posts = [p.get('do') for p in got['posts'] if isinstance(p, dict)]
        self.assertEqual(posts, ['ready', 'save', 'close'])


class BoardNativeTests(unittest.TestCase):
    def test_app_wiring(self):
        app = native_source()
        board = (ROOT / 'Sources/Rabik/Board/Board.swift').read_text()
        speaker = (ROOT / 'Sources/Rabik/Overlay/Speaker.swift').read_text()
        self.assertIn('if line.hasPrefix("◫ ") {', app)
        self.assertIn('self.board.receive(String(line.dropFirst(2))); continue', app)
        self.assertIn('if board.visible, let shown = board.summary { request["board"] = shown }', app)   # follow-ups see it
        self.assertIn('board.onAsk = { [weak self] question in self?.typed(question) }', app)
        self.assertIn('if was { board.flush() }', app)   # speech stopped: the drawing finishes
        self.assertIn('func say(_ sentences: [String], voice: AVSpeechSynthesisVoice?, started: ((Double) -> Void)? = nil)', speaker)
        self.assertIn('if let next = queued.first { next.started?(next.seconds) }', speaker)
        self.assertIn('guard let buffer, let player else { started?(Speaker.readingTime(sentence)); finished(g); return }', speaker)
        self.assertIn('if speak?(text, start) != true {', board)   # voice off: reading pace
        self.assertIn('loadPage(v, "board.html")', board)
        self.assertIn('final class BoardPanel: NSPanel { override var canBecomeKey: Bool { false } }', board)

    def test_the_card_sits_right_of_the_middle_and_on_screen(self):
        src = (ROOT / 'Sources/Rabik/Board/Board.swift').read_text()
        frame = src[src.index('    static func frame(in vf: NSRect) -> NSRect {'):src.index('    private func make() {')]
        code = 'import Cocoa\nenum Board {\n' + frame + '}\n' + r'''
for vf in [NSRect(x: 0, y: 0, width: 1512, height: 944), NSRect(x: 1512, y: 0, width: 2560, height: 1415), NSRect(x: 0, y: 0, width: 1024, height: 700)] {
    let f = Board.frame(in: vf)
    print(f.midX > vf.midX, vf.contains(f), f.width <= 780, f.height <= 520)
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src_path, binary = Path(tmp) / 'f.swift', Path(tmp) / 'f'
            src_path.write_text(code)
            built = subprocess.run(['swiftc', str(src_path), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.stdout.split('\n')[:3], ['true true true true'] * 3)

    def test_voice_is_on_by_default_with_a_mute_button(self):
        prefs = (ROOT / 'Sources/Rabik/Core/Prefs.swift').read_text()
        self.assertIn('"speak": true, "voice": "",', prefs)
        self.assertIn('if saved["speakDefaulted"] == nil { values["speak"] = true; values["speakDefaulted"] = true }', prefs)
        app, page = native_source(), (ROOT / 'ui/ui.html').read_text()
        self.assertIn('if let on = b["voice"] as? Bool { Prefs.set("speak", on); if !on { shush() }', app)
        self.assertIn('js("voice", Prefs.bool("speak"))', app)
        self.assertIn('<div id="voice" role="button"', page)
        self.assertIn("if (el?.closest('#voice')) return toggleVoice();", page)   # the box never activates: native taps reach it


if __name__ == '__main__':
    unittest.main()
