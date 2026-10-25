"""Meeting language and live translation: Apple's on-device speech in the language chosen in Settings (its dictation model where
the transcription one lacks the language), and the other side's lines translated under them on this Mac."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
from tests import native_source
from tests.test_settings_page import HARNESS

ROOT = Path(__file__).resolve().parents[1]


class MeetingLanguageTests(unittest.TestCase):
    def test_the_call_is_heard_in_the_chosen_language(self):
        speech, meeting = (ROOT / 'Sources/Rabik/Meeting/MeetingSpeech.swift').read_text(), (ROOT / 'Sources/Rabik/Meeting/Meeting.swift').read_text()
        self.assertIn('let chosen = Prefs.str("meetingLanguage")', speech)
        self.assertIn('[chosen.isEmpty ? Locale.current : Locale(identifier: chosen), Locale(identifier: "en-US")]', speech)   # Automatic: the Mac's language
        self.assertIn('DictationTranscriber(locale: locale, preset: .progressiveLongDictation)', speech)   # Turkish: no SpeechTranscriber
        self.assertIn('let locale = await MeetingSpeech.locale()', meeting)
        self.assertNotIn('Locale(identifier: "en-US")', meeting)
        self.assertIn('// enum MeetingSpeech lives in Meeting/MeetingSpeech.swift', (ROOT / 'Sources/Rabik/main.swift').read_text())

    def test_both_start_off_or_automatic(self):
        source = native_source()
        defaults = source[source.index('static let defaults'):source.index('static let retiredKeys')]
        self.assertIn('"meetingLanguage": ""', defaults)
        self.assertIn('"meetingTranslate": false', defaults)

    def test_only_their_lines_are_translated_and_a_missing_language_says_so_once(self):
        speech, meeting = (ROOT / 'Sources/Rabik/Meeting/MeetingSpeech.swift').read_text(), (ROOT / 'Sources/Rabik/Meeting/Meeting.swift').read_text()
        self.assertIn('guard Prefs.bool("meetingTranslate"), let source = locale.language.languageCode, source != Locale.current.language.languageCode', speech)
        self.assertIn('TranslationSession(installedSource: locale.language, target: Locale.current.language)', speech)
        self.assertIn('if !you, let session = translator, !translationFailed {', meeting)
        self.assertIn('await previous?.value', meeting)   # one translation at a time, in order
        self.assertIn('Translation Languages', meeting)

    def test_the_summary_keeps_the_meetings_language(self):
        self.assertIn('Summarize this meeting transcript, in its own language.', (ROOT / 'brain/meeting.py').read_text())


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class MeetingPanelTranslationTests(unittest.TestCase):
    def test_a_translation_sits_under_its_line_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'page.swift').write_text(HARNESS.replace('name: "st"', 'name: "meeting"'))
            built = subprocess.run(['swiftc', str(tmp / 'page.swift'), '-o', str(tmp / 'page')], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            page = (ROOT / 'ui/meeting.html').read_text().replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text())
            (tmp / 'meeting.html').write_text(page)
            script = """for (let i = 0; i < 150 && !window.meeting; i++) await new Promise(r => setTimeout(r, 20));
                meeting.listen(); meeting.line({id: 'l1', text: 'Bütçe on sekiz bin.', seconds: 3}); meeting.line({id: 'l2', text: 'Mine', seconds: 4, mic: true});
                meeting.translated({id: 'l1', text: 'The budget is eighteen thousand.'}); meeting.translated({id: 'l1', text: 'again'});
                meeting.translated({id: 'l2', error: 'Translation needs both languages.'});
                const line = document.querySelector('[data-id="l1"]');
                return [line.querySelector('.text').firstChild.textContent, [...line.querySelectorAll('.tr')].map(t => t.textContent), document.getElementById('toast').textContent];"""
            p = subprocess.run([str(tmp / 'page'), str(tmp / 'meeting.html'), script], capture_output=True, text=True, timeout=30,
                               env={**os.environ, 'RABIK_DIR': str(tmp)})
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            out = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertEqual(out['result'], ['Bütçe on sekiz bin.', ['The budget is eighteen thousand.'], 'Translation needs both languages.'])


if __name__ == '__main__':
    unittest.main()
