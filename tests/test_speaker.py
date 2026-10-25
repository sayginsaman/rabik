"""Spoken answers: the Siri voice or the Mac's natural voices, sentence by sentence while the answer streams, through Rabik's
own audio engine so "Stop when I talk" can cancel its own voice out of the mic and stop when the user speaks."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
from tests import native_source, run_swift

ROOT = Path(__file__).resolve().parents[1]
SPEAKER = (ROOT / 'Sources/Rabik/Overlay/Speaker.swift').read_text()


class SpeakerTests(unittest.TestCase):
    def test_settings_default_to_siri_and_stopping_when_you_talk(self):
        source = native_source()
        defaults = source[source.index('static let defaults'):source.index('static let retiredKeys')]
        self.assertIn('"speak": false, "voice": "", "bargeIn": true,', defaults)
        page = (ROOT / 'ui/settings.html').read_text()
        self.assertIn('<select data-k="voice" id="voice" aria-label="Voice"></select>', page)
        self.assertIn('<input type="checkbox" data-k="bargeIn">', page)
        self.assertIn('d["voices"] = Speaker.voices()', source)

    def test_the_voice_follows_the_answers_language(self):
        swift = SPEAKER.split('import NaturalLanguage', 1)[1] + r'''
enum Prefs { static var picked = ""; static func str(_ k: String) -> String { k == "voice" ? picked : "" }; static func bool(_ k: String) -> Bool { false } }
precondition(Speaker.voice(for: "en") == nil, "English should be the Siri voice")
precondition(Speaker.voice(for: nil) == nil && Speaker.voice(for: "und") == nil, "an unknown language should stay on Siri")
if let tr = Speaker.voice(for: "tr") { precondition(tr.language.hasPrefix("tr"), "a Turkish answer got \(tr.language)") }
if let fr = AVSpeechSynthesisVoice.speechVoices().first(where: { $0.language.hasPrefix("fr") }) {
    Prefs.picked = fr.identifier
    precondition(Speaker.voice(for: "fr")?.identifier == fr.identifier, "the picked voice was not used for its language")
    precondition(Speaker.voice(for: "en")?.language.hasPrefix("en") == true, "an English answer kept a French voice")
}
precondition(Speaker.sentences("One. Two! Three") == ["One.", "Two!", "Three"])
precondition(Speaker.language(of: "Bugün hava çok güzel, dışarı çıkalım mı?") == "tr")
print("voices ok")
'''
        self.assertIn('voices ok', run_swift(self, 'import Foundation\nimport AVFoundation\nimport NaturalLanguage\n' + swift, timeout=30))

    def test_its_own_voice_is_cancelled_out_and_your_voice_stops_it(self):
        self.assertIn('try e.inputNode.setVoiceProcessingEnabled(true)', SPEAKER)
        self.assertIn('let listen = Prefs.bool("bargeIn") && AVCaptureDevice.authorizationStatus(for: .audio) == .authorized', SPEAKER)   # never asks for the mic
        self.assertIn('guard db > -38 else { loudSince = nil; return }', SPEAKER)
        self.assertIn('if let since = loudSince, Date().timeIntervalSince(since) >= 0.3 { stop(); onInterrupted?() }', SPEAKER)
        self.assertIn('e.attach(p); e.connect(p, to: e.mainMixerNode, format: Speaker.format)', SPEAKER)   # played by Rabik, so the canceller knows it

    def test_the_streamed_answer_starts_speaking_and_a_rewrite_starts_over(self):
        app = (ROOT / 'Sources/Rabik/Overlay/App.swift').read_text()
        self.assertIn('if line.hasPrefix("… "), Prefs.bool("speak"), !guided { self.speakAhead(', app)
        self.assertIn('guard done.starts(with: said) else { shush(); return }', app)
        self.assertIn('if said.isEmpty || !all.starts(with: said) { shush();', app)
        self.assertIn('ringGone == nil, !speaker.speaking else {', app)   # the box stays while it talks
        self.assertIn('app.speaker.speaking', (ROOT / 'Sources/Rabik/App/Updater.swift').read_text())


if __name__ == '__main__':
    unittest.main()
