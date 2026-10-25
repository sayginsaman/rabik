// Meeting language and live translation. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa
import Carbon
import AVFoundation
import Speech
import WebKit
import ScreenCaptureKit
import Vision
import PDFKit
import QuickLookThumbnailing
import UniformTypeIdentifiers
import EventKit
import CoreAudio
import AudioToolbox

import Translation

// Settings → Meetings → Language: Apple's on-device speech for the call and the mic, in the language chosen. SpeechTranscriber where
// it knows the language, its dictation model where it does not (Turkish is one). Automatic: the Mac's own language if either knows it,
// else US English. Translate the call: the other side's lines, into the Mac's language, also on this Mac.
enum MeetingSpeech {
    static var languages: [[String: String]] = []   // Settings' choices, [{id, name}], read once at launch
    static func load(_ done: @escaping () -> Void) {
        Task.detached {
            let ids = Set((await SpeechTranscriber.supportedLocales + DictationTranscriber.supportedLocales).map { $0.identifier(.bcp47) })
            let rows = ids.map { ["id": $0, "name": Locale.current.localizedString(forIdentifier: $0) ?? $0] }.sorted { $0["name"]! < $1["name"]! }
            await MainActor.run { languages = rows; done() }
        }
    }
    static func locale() async -> Locale {
        let chosen = Prefs.str("meetingLanguage")
        for wanted in [chosen.isEmpty ? Locale.current : Locale(identifier: chosen), Locale(identifier: "en-US")] {
            if let found = await SpeechTranscriber.supportedLocale(equivalentTo: wanted) { return found }
            if let found = await DictationTranscriber.supportedLocale(equivalentTo: wanted) { return found }
        }
        return Locale(identifier: "en-US")
    }
    // One transcriber, and its words as (text, final), from whichever model knows the language.
    static func transcriber(_ locale: Locale) async -> (module: any SpeechModule, words: AsyncThrowingStream<(String, Bool), Error>) {
        if await SpeechTranscriber.supportedLocale(equivalentTo: locale) != nil {
            let t = SpeechTranscriber(locale: locale, preset: .progressiveTranscription)
            return (t, words(t.results) { (String($0.text.characters), $0.isFinal) })
        }
        let d = DictationTranscriber(locale: locale, preset: .progressiveLongDictation)
        return (d, words(d.results) { (String($0.text.characters), $0.isFinal) })
    }
    static func words<S: AsyncSequence & Sendable>(_ results: S, _ read: @escaping @Sendable (S.Element) -> (String, Bool)) -> AsyncThrowingStream<(String, Bool), Error> where S.Element: Sendable {
        AsyncThrowingStream { out in
            let task = Task { do { for try await r in results { out.yield(read(r)) }; out.finish() } catch { out.finish(throwing: error) } }
            out.onTermination = { _ in task.cancel() }
        }
    }
    static func translator(from locale: Locale) -> TranslationSession? {   // nil: off, or the call is already in the Mac's language
        guard Prefs.bool("meetingTranslate"), let source = locale.language.languageCode, source != Locale.current.language.languageCode else { return nil }
        return TranslationSession(installedSource: locale.language, target: Locale.current.language)
    }
}
