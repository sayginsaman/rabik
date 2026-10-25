// Spoken answers. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa
import AVFoundation
import NaturalLanguage

// Settings → Read answers aloud: sentence by sentence through Rabik's own audio engine, so speaking starts before the answer
// ends. Automatic is the Siri voice `say` uses (AVSpeechSynthesizer can't use Siri voices); a picked voice, or the best one
// installed for an answer in another language, comes from AVSpeechSynthesizer. With "Stop when I talk" the mic listens while it
// speaks, through Apple's voice processing (echo cancellation), so Rabik's own voice never counts as you and nothing is recorded.
final class Speaker {
    static let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 22050, channels: 1, interleaved: false)!
    var onIdle: (() -> Void)?   // the last queued sentence was spoken
    var onInterrupted: (() -> Void)?   // the user started talking over it
    private(set) var speaking = false
    private var engine: AVAudioEngine?, player: AVAudioPlayerNode?
    private var generation = 0, pending = 0, loudSince: Date?, startedAt = Date.distantPast
    private let render = DispatchQueue(label: "rabik.speaker")
    private let synth = AVSpeechSynthesizer()

    // Settings' Voice list: the natural voices installed on this Mac (Premium and Enhanced).
    static func voices() -> [[String: String]] {
        AVSpeechSynthesisVoice.speechVoices().filter { $0.quality != .default }
            .sorted { ($0.language, $1.quality.rawValue, $0.name) < ($1.language, $0.quality.rawValue, $1.name) }
            .map { ["id": $0.identifier, "name": "\($0.name)\($0.quality == .premium ? " (Premium)" : " (Enhanced)") · \(Locale.current.localizedString(forIdentifier: $0.language) ?? $0.language)"] }
    }

    // nil: the Siri voice. The picked voice when it speaks the answer's language, else the best voice installed for it.
    static func voice(for language: String?) -> AVSpeechSynthesisVoice? {
        let picked = Prefs.str("voice").isEmpty ? nil : AVSpeechSynthesisVoice(identifier: Prefs.str("voice"))
        guard let language, language != "und" else { return picked }
        if let picked, picked.language.hasPrefix(language) { return picked }
        if picked == nil && language == "en" { return nil }   // Siri speaks English
        let region = Locale.current.region?.identifier ?? ""
        return AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix(language) }
            .max { ($0.quality.rawValue, $0.language.hasSuffix(region) ? 1 : 0) < ($1.quality.rawValue, $1.language.hasSuffix(region) ? 1 : 0) }
    }

    static func language(of text: String) -> String? { NLLanguageRecognizer.dominantLanguage(for: text)?.rawValue }

    static func sentences(_ text: String) -> [String] {
        let tokenizer = NLTokenizer(unit: .sentence); tokenizer.string = text
        return tokenizer.tokens(for: text.startIndex..<text.endIndex).map { text[$0].trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    }

    func say(_ sentences: [String], voice: AVSpeechSynthesisVoice?) {
        guard !sentences.isEmpty else { return }
        if !speaking { begin() }
        let g = generation
        for sentence in sentences {
            pending += 1
            render.async { [weak self] in
                guard let self else { return }
                let buffer = self.render(sentence, voice)
                DispatchQueue.main.async { [weak self] in
                    guard let self, generation == g else { return }
                    guard let buffer, let player else { finished(g); return }
                    player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in DispatchQueue.main.async { self?.finished(g) } }
                    if !player.isPlaying { player.play() }
                }
            }
        }
    }

    func stop() {
        guard speaking else { return }
        generation += 1; pending = 0; speaking = false; loudSince = nil
        player?.stop(); engine?.inputNode.removeTap(onBus: 0); engine?.stop(); engine = nil; player = nil
    }

    private func finished(_ g: Int) {
        guard g == generation else { return }
        pending -= 1
        if pending <= 0 { stop(); onIdle?() }
    }

    private func begin() {
        speaking = true; startedAt = Date()
        let e = AVAudioEngine(), p = AVAudioPlayerNode()
        let listen = Prefs.bool("bargeIn") && AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        if listen {   // must be set before the engine starts; it also cancels the player's sound out of the mic
            do {
                try e.inputNode.setVoiceProcessingEnabled(true)
                e.inputNode.voiceProcessingOtherAudioDuckingConfiguration = .init(enableAdvancedDucking: false, duckingLevel: .min)
            } catch {}
        }
        e.attach(p); e.connect(p, to: e.mainMixerNode, format: Speaker.format)
        if listen && e.inputNode.isVoiceProcessingEnabled {
            let g = generation
            e.inputNode.installTap(onBus: 0, bufferSize: 1024, format: e.inputNode.outputFormat(forBus: 0)) { [weak self] buffer, _ in
                guard let data = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return }
                var sum: Float = 0
                for i in 0..<Int(buffer.frameLength) { sum += data[i] * data[i] }
                let db = 10 * log10(max(sum / Float(buffer.frameLength), 1e-10))
                DispatchQueue.main.async { self?.heard(db, g) }
            }
        }
        do { try e.start() } catch { speaking = false; e.inputNode.removeTap(onBus: 0); return }
        engine = e; player = p
    }

    // About 0.3 s of the user's voice (Rabik's own is cancelled out) stops it; the first 0.3 s are the canceller settling.
    private func heard(_ db: Float, _ g: Int) {
        guard g == generation, speaking, Date().timeIntervalSince(startedAt) > 0.3 else { return }
        guard db > -38 else { loudSince = nil; return }
        if loudSince == nil { loudSince = Date() }
        if let since = loudSince, Date().timeIntervalSince(since) >= 0.3 { stop(); onInterrupted?() }
    }

    func render(_ text: String, _ voice: AVSpeechSynthesisVoice?) -> AVAudioPCMBuffer? { voice.map { synthesize(text, $0) } ?? siri(text) }   // in Speaker.format

    private func siri(_ text: String) -> AVAudioPCMBuffer? {
        let out = NSTemporaryDirectory() + "rabik-say-\(UUID().uuidString).aiff"
        defer { try? FileManager.default.removeItem(atPath: out) }
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/say"); p.arguments = ["-o", out, "--", text]
        do { try p.run() } catch { return nil }
        p.waitUntilExit()
        guard p.terminationStatus == 0, let file = try? AVAudioFile(forReading: URL(fileURLWithPath: out)),
              let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length)),
              (try? file.read(into: buffer)) != nil else { return nil }
        return Speaker.convert(buffer)
    }

    private func synthesize(_ text: String, _ voice: AVSpeechSynthesisVoice) -> AVAudioPCMBuffer? {
        let utterance = AVSpeechUtterance(string: text); utterance.voice = voice
        let done = DispatchSemaphore(value: 0)
        var parts: [AVAudioPCMBuffer] = []
        synth.write(utterance) { buffer in
            guard let pcm = buffer as? AVAudioPCMBuffer, pcm.frameLength > 0 else { done.signal(); return }
            if let converted = Speaker.convert(pcm) { parts.append(converted) }
        }
        guard done.wait(timeout: .now() + 20) == .success, !parts.isEmpty else { return nil }
        let total = parts.reduce(0) { $0 + $1.frameLength }
        guard let joined = AVAudioPCMBuffer(pcmFormat: Speaker.format, frameCapacity: total) else { return nil }
        for part in parts {
            memcpy(joined.floatChannelData![0] + Int(joined.frameLength), part.floatChannelData![0], Int(part.frameLength) * MemoryLayout<Float>.size)
            joined.frameLength += part.frameLength
        }
        return joined
    }

    static func convert(_ buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        guard let converter = AVAudioConverter(from: buffer.format, to: format) else { return nil }
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * format.sampleRate / buffer.format.sampleRate) + 1024
        guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return nil }
        var given = false
        _ = converter.convert(to: out, error: nil) { _, status in
            if given { status.pointee = .endOfStream; return nil }
            given = true; status.pointee = .haveData; return buffer
        }
        return out.frameLength > 0 ? out : nil
    }
}
