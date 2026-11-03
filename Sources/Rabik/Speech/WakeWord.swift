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
    private let mic = Mic()   // only the chosen mic (Audio.swift): never flips Bluetooth headphones into call mode
    private var request: SFSpeechAudioBufferRecognitionRequest?, task: SFSpeechRecognitionTask?
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

    private func wait() { retryAt = Date().addingTimeInterval(backoff); backoff = min(backoff * 2, 120) }

    private func begin() {
        guard let recognizer, let device = listenMic().flatMap({ AVCaptureDevice(uniqueID: $0.uid) }) ?? AVCaptureDevice.default(for: .audio) else { return }
        let r = SFSpeechAudioBufferRecognitionRequest()
        r.shouldReportPartialResults = true; r.taskHint = .search; r.contextualStrings = ["Hey Rabik", "Rabik"]
        r.requiresOnDeviceRecognition = true   // never sent to a server (check() starts only where this Mac can do it)
        request = r; listening = true; began = Date()
        mic.start(device, sampleRate: 16000, { buffer in r.append(buffer) }) { [weak self] result in
            guard let self, request === r, case .failure = result else { return }
            wait(); end()   // the mic would not open: try again later, not every second
        }
        task = recognizer.recognitionTask(with: r) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString ?? "", done = error != nil || result?.isFinal == true
            DispatchQueue.main.async { [weak self] in
                guard let self, request === r else { return }
                if WakeWord.heard(text) { backoff = 5; end(); onWake(); return }
                if done {   // check() starts a fresh one; one that failed at once waits longer each time, so the mic never flickers
                    if Date().timeIntervalSince(began) < 3 { wait() } else { backoff = 5 }
                    end()
                }
            }
        }
        limit = Timer.scheduledTimer(withTimeInterval: 50, repeats: false) { [weak self] _ in self?.end() }
    }

    func end() {
        limit?.invalidate(); limit = nil
        task?.cancel(); request?.endAudio(); mic.stop()
        request = nil; task = nil; listening = false
    }
}
