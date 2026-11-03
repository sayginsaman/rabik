// "Hey Rabik". Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa
import AVFoundation
import Speech

// Settings → Voice → "Hey Rabik" (off by default: the mic stays on, so macOS shows its orange dot). While Rabik is idle it
// listens with on-device speech recognition only (nothing leaves this Mac, nothing is saved) for "Hey Rabik"; hearing it starts
// an ask like the mic button, which ends after a pause. It never listens while Rabik is listening, answering or speaking, in a
// meeting, while paused, or with the screen locked; each recognition runs at most 50 s and starts fresh.
final class WakeWord {
    var canListen: () -> Bool = { false }
    var onWake: () -> Void = {}
    private(set) var listening = false
    private var engine: AVAudioEngine?, request: SFSpeechAudioBufferRecognitionRequest?, task: SFSpeechRecognitionTask?
    private var poll: Timer?, limit: Timer?, locked = false, began = Date.distantPast, retryAt = Date.distantPast, backoff = 5.0
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))

    // "hey rabik" and how English recognition hears it ("hey rabbit", "hey Robik", "hey Rebecca"); it must be said as a greeting.
    static func heard(_ text: String) -> Bool {
        text.lowercased().range(of: #"\b(hey|hi|okay|ok)[,.!]?\s+(ra+bb?[iey]+[ck]+|rabbit|robb?[iy][ck]|rabic|rebecca|rob[ie]?k|rah ?bick|reb[ie]k)\b"#, options: .regularExpression) != nil
    }

    func start() {
        guard poll == nil else { return }
        let center = DistributedNotificationCenter.default()
        center.addObserver(forName: .init("com.apple.screenIsLocked"), object: nil, queue: .main) { [weak self] _ in self?.locked = true; self?.check() }
        center.addObserver(forName: .init("com.apple.screenIsUnlocked"), object: nil, queue: .main) { [weak self] _ in self?.locked = false; self?.check() }
        poll = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.check() }
    }

    private func check() {
        let want = Prefs.bool("wakeWord") && !Prefs.bool("paused") && !locked && canListen()
            && AVCaptureDevice.authorizationStatus(for: .audio) == .authorized && SFSpeechRecognizer.authorizationStatus() == .authorized
            && recognizer?.isAvailable == true && recognizer?.supportsOnDeviceRecognition == true && Date() >= retryAt
        if want && !listening { begin() } else if !want && listening { end() }
    }

    private func begin() {
        guard let recognizer else { return }
        let e = AVAudioEngine(), r = SFSpeechAudioBufferRecognitionRequest()
        r.shouldReportPartialResults = true; r.taskHint = .search; r.contextualStrings = ["Hey Rabik", "Rabik"]
        r.requiresOnDeviceRecognition = true   // never sent to a server (check() starts only where this Mac can do it)
        let input = e.inputNode, format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { return }
        input.installTap(onBus: 0, bufferSize: 2048, format: format) { buffer, _ in r.append(buffer) }
        do { try e.start() } catch { input.removeTap(onBus: 0); return }
        engine = e; request = r; listening = true; began = Date()
        task = recognizer.recognitionTask(with: r) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString ?? "", done = error != nil || result?.isFinal == true
            DispatchQueue.main.async { [weak self] in
                guard let self, request === r else { return }
                if WakeWord.heard(text) { backoff = 5; end(); onWake(); return }
                if done {   // check() starts a fresh one; one that failed at once waits longer each time, so the mic never flickers
                    if Date().timeIntervalSince(began) < 3 { retryAt = Date().addingTimeInterval(backoff); backoff = min(backoff * 2, 120) } else { backoff = 5 }
                    end()
                }
            }
        }
        limit = Timer.scheduledTimer(withTimeInterval: 50, repeats: false) { [weak self] _ in self?.end() }
    }

    func end() {
        limit?.invalidate(); limit = nil
        task?.cancel(); request?.endAudio()
        engine?.inputNode.removeTap(onBus: 0); engine?.stop()
        engine = nil; request = nil; task = nil; listening = false
    }
}
