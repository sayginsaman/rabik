// "Hey Rabik". Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa
import AVFoundation
import Speech

// Settings → Voice → "Hey Rabik" (off by default: the mic stays on, so macOS shows its orange dot). While Rabik is idle it
// listens for "Hey Rabik" with the same on-device model as asks (SpeechAnalyzer: nothing leaves this Mac, nothing is saved, and
// no Speech Recognition permission of its own). Hearing it starts an ask like the mic button, which ends after a pause. It never
// listens while Rabik is listening, answering or speaking, taking meeting notes, while paused, or with the screen locked; each
// listen runs at most 50 s and starts fresh.
final class WakeWord {
    var canListen: () -> Bool = { false }
    var onWake: () -> Void = {}
    private(set) var listening = false
    private let mic = Mic()   // only the chosen mic (Audio.swift): never flips Bluetooth headphones into call mode
    private var inputs: AsyncStream<AnalyzerInput>.Continuation?, analyzer: SpeechAnalyzer?, reading: Task<Void, Never>?, format: AVAudioFormat?
    private var poll: Timer?, limit: Timer?, locked = false, began = Date.distantPast, retryAt = Date.distantPast, backoff = 5.0, generation = 0
    private static let english = Locale(identifier: "en-US")   // SpeechTranscriber's locale for asks too (App.speechModule)
    private static func module() -> SpeechTranscriber { SpeechTranscriber(locale: english, transcriptionOptions: [], reportingOptions: [.volatileResults], attributeOptions: []) }

    // "Hey Rabik" as English recognition hears it: a greeting, then one or two words with Rabik's sounds, r-b-k with any vowels
    // ("Hey, Ravik", "Hey Rabbic", "Hey, Rob Eag" for ra-BEEK, "hey Rubik", "hey Rebecca"), or one of its own words for it.
    static func heard(_ text: String) -> Bool {
        let words = text.lowercased().components(separatedBy: CharacterSet.letters.inverted).filter { !$0.isEmpty }
        for (i, w) in words.enumerated() where ["hey", "hi", "hay", "okay", "ok"].contains(w) {
            let next = Array(words.dropFirst(i + 1).prefix(2))
            guard let first = next.first else { continue }
            if ["rabbit", "rabbi", "robbie"].contains(first) || ["rbk", "rbks"].contains(sounds(first)) || next.count == 2 && sounds(next.joined()) == "rbk" { return true }
        }
        return false
    }

    // A word's consonants as recognition confuses them (v, p → b; c, g, q, x → k), vowels dropped, doubles as one: "ravik" → "rbk".
    static func sounds(_ word: String) -> String {
        var out = ""
        for ch in word {
            let c: Character? = "aeiouyhw".contains(ch) ? nil : "vpb".contains(ch) ? "b" : "cgqkx".contains(ch) ? "k" : ch
            if let c, out.last != c { out.append(c) }
        }
        return out
    }

    func start() {
        guard poll == nil else { return }
        let center = DistributedNotificationCenter.default()
        center.addObserver(forName: .init("com.apple.screenIsLocked"), object: nil, queue: .main) { [weak self] _ in self?.locked = true; self?.check() }
        center.addObserver(forName: .init("com.apple.screenIsUnlocked"), object: nil, queue: .main) { [weak self] _ in self?.locked = false; self?.check() }
        poll = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.check() }
        Task { [weak self] in   // the model asks use, installed if missing, and the audio format it wants
            let m = WakeWord.module()
            if let r = try? await AssetInventory.assetInstallationRequest(supporting: [m]) { try? await r.downloadAndInstall() }
            let f = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [m])
            await MainActor.run { self?.format = f }
        }
    }

    private func check() {
        let want = Prefs.bool("wakeWord") && !Prefs.bool("paused") && !locked && canListen() && format != nil
            && AVCaptureDevice.authorizationStatus(for: .audio) == .authorized && Date() >= retryAt
        if want && !listening { begin() } else if !want && listening { end() }
    }

    private func wait() { retryAt = Date().addingTimeInterval(backoff); backoff = min(backoff * 2, 120) }

    private func begin() {
        guard let format, let device = listenMic().flatMap({ AVCaptureDevice(uniqueID: $0.uid) }) ?? AVCaptureDevice.default(for: .audio) else { return }
        generation += 1; let g = generation
        let transcriber = WakeWord.module(), an = SpeechAnalyzer(modules: [transcriber])
        let (stream, feed) = AsyncStream<AnalyzerInput>.makeStream()
        inputs = feed; analyzer = an; listening = true; began = Date()
        let ctx = AnalysisContext(); ctx.contextualStrings[.general] = ["Hey Rabik", "Rabik"]
        Task { try? await an.setContext(ctx); try? await an.start(inputSequence: stream) }
        let convert = speechConverter(to: format)
        mic.start(device, sampleRate: format.sampleRate, { buffer in feed.yield(AnalyzerInput(buffer: convert(buffer))) }) { [weak self] result in
            guard let self, generation == g, case .failure = result else { return }
            wait(); end()   // the mic would not open: try again later, not every second
        }
        reading = Task { [weak self] in
            var said = ""   // the finished phrases so far: "Hey." and "Rabik" can land in two
            do {
                for try await r in transcriber.results {
                    let text = String(r.text.characters)
                    if WakeWord.heard(said + " " + text) {
                        await MainActor.run { guard let self, self.generation == g else { return }; self.backoff = 5; self.end(); self.onWake() }
                        return
                    }
                    if r.isFinal { said = String((said + " " + text).suffix(40)) }
                }
            } catch {}
            await MainActor.run {   // the model stopped: check() starts a fresh one; one that failed at once waits longer each time
                guard let self, self.generation == g else { return }
                if Date().timeIntervalSince(self.began) < 3 { self.wait() } else { self.backoff = 5 }
                self.end()
            }
        }
        limit = Timer.scheduledTimer(withTimeInterval: 50, repeats: false) { [weak self] _ in self?.end() }
    }

    func end() {
        generation += 1
        limit?.invalidate(); limit = nil
        inputs?.finish(); inputs = nil; mic.stop()
        reading?.cancel(); reading = nil
        if let an = analyzer { Task { await an.cancelAndFinishNow() } }
        analyzer = nil; listening = false
    }
}

