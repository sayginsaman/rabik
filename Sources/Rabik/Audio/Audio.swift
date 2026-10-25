// Microphones, the meeting/dictation input, and quieting other audio while listening. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

struct MicrophoneDevice {
    let id: AudioDeviceID, uid: String, name: String, transport: UInt32
}

// Opens only the chosen mic. AVAudioEngine opens the default input first, which flips Bluetooth headphones into call mode and keeps them there.
final class Mic: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    private var session: AVCaptureSession?, onBuffer: ((AVAudioPCMBuffer) -> Void)?
    private let queue = DispatchQueue(label: "rabik.mic")
    private let sessionQueue = DispatchQueue(label: "rabik.mic.session")
    private var generation = 0
    private(set) var isRunning = false
    func start(_ device: AVCaptureDevice, sampleRate: Double, _ onBuffer: @escaping (AVAudioPCMBuffer) -> Void, completion: @escaping (Result<Void, Error>) -> Void) {
        stop()
        isRunning = true; let g = generation
        sessionQueue.async { [self] in
            let result: Result<Void, Error>
            do {
                let s = AVCaptureSession(), input = try AVCaptureDeviceInput(device: device), out = AVCaptureAudioDataOutput()
                guard s.canAddInput(input), s.canAddOutput(out) else { throw NSError(domain: "Mic", code: 1, userInfo: [NSLocalizedDescriptionKey: "\(device.localizedName) can't be opened"]) }
                s.addInput(input); s.addOutput(out)
                out.audioSettings = [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: sampleRate, AVNumberOfChannelsKey: 1,
                                     AVLinearPCMBitDepthKey: 32, AVLinearPCMIsFloatKey: true, AVLinearPCMIsNonInterleaved: true]
                out.setSampleBufferDelegate(self, queue: queue)
                queue.sync { self.onBuffer = onBuffer }; session = s
                s.startRunning()
                guard s.isRunning else { throw NSError(domain: "Mic", code: 2, userInfo: [NSLocalizedDescriptionKey: "\(device.localizedName) could not start"]) }
                result = .success(())
            } catch { result = .failure(error) }
            DispatchQueue.main.async { [self] in
                guard generation == g else { return }
                if case .failure = result { stop() }
                completion(result)
            }
        }
    }
    func stop(completion: @escaping () -> Void = {}) {
        generation += 1; isRunning = false
        sessionQueue.async { [self] in
            session?.stopRunning(); session = nil   // release the device so headphones return to music mode
            queue.sync { onBuffer = nil }
            DispatchQueue.main.async(execute: completion)
        }
    }
    func captureOutput(_ output: AVCaptureOutput, didOutput sample: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let onBuffer, let desc = sample.formatDescription, let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc),
              let format = AVAudioFormat(streamDescription: asbd),
              let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(sample.numSamples)) else { return }
        buf.frameLength = buf.frameCapacity
        guard CMSampleBufferCopyPCMDataIntoAudioBufferList(sample, at: 0, frameCount: Int32(sample.numSamples), into: buf.mutableAudioBufferList) == noErr else { return }
        onBuffer(buf)
    }
}

struct AudioVolumeSnapshot: Codable, Equatable {
    let uid: String, selector: UInt32, volume: Float32
    let owner: Int32
}

protocol AudioVolumeLayer {
    func snapshot() -> AudioVolumeSnapshot?
    @discardableResult func set(_ snapshot: AudioVolumeSnapshot, volume: Float32) -> Bool
}

struct CoreAudioVolume: AudioVolumeLayer {
    func snapshot() -> AudioVolumeSnapshot? {
        let sys = AudioObjectID(kAudioObjectSystemObject)
        guard let device = audioProp(sys, kAudioHardwarePropertyDefaultOutputDevice, AudioDeviceID(0)).first,
              device != 0, let uid = audioString(device, kAudioDevicePropertyDeviceUID) else { return nil }
        for selector in [kAudioHardwareServiceDeviceProperty_VirtualMainVolume, kAudioDevicePropertyVolumeScalar] {
            var a = AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioDevicePropertyScopeOutput, mElement: kAudioObjectPropertyElementMain)
            var settable: DarwinBoolean = false, value: Float32 = 0, size = UInt32(MemoryLayout<Float32>.size)
            if AudioObjectHasProperty(device, &a), AudioObjectIsPropertySettable(device, &a, &settable) == noErr, settable.boolValue,
               AudioObjectGetPropertyData(device, &a, 0, nil, &size, &value) == noErr {
                return AudioVolumeSnapshot(uid: uid, selector: selector, volume: value, owner: getpid())
            }
        }
        return nil   // HDMI and other fixed-volume outputs cannot be safely quieted.
    }
    func set(_ snapshot: AudioVolumeSnapshot, volume: Float32) -> Bool {
        guard let device = audioProp(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyDevices, AudioDeviceID(0)).first(where: {
            audioString($0, kAudioDevicePropertyDeviceUID) == snapshot.uid
        }) else { return false }
        var a = AudioObjectPropertyAddress(mSelector: snapshot.selector, mScope: kAudioDevicePropertyScopeOutput, mElement: kAudioObjectPropertyElementMain)
        var value = volume
        return AudioObjectSetPropertyData(device, &a, 0, nil, UInt32(MemoryLayout<Float32>.size), &value) == noErr
    }
}

final class AudioQuiet {
    let layer: any AudioVolumeLayer
    var changed: (AudioVolumeSnapshot?) -> Void
    private let later: (TimeInterval, @escaping () -> Void) -> Void
    private var original: AudioVolumeSnapshot?, scale: Float32 = 1, generation = 0, active = false
    init(layer: any AudioVolumeLayer, changed: @escaping (AudioVolumeSnapshot?) -> Void = { _ in },
         later: @escaping (TimeInterval, @escaping () -> Void) -> Void = { delay, work in DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work) }) {
        self.layer = layer; self.changed = changed; self.later = later
    }
    func begin(_ enabled: Bool, level: Float32 = 0.18) {
        guard enabled else { return }
        if original == nil {
            guard let snapshot = layer.snapshot() else { return }
            original = snapshot; scale = 1; changed(snapshot)
        }
        active = true; ramp(to: level)
    }
    func end(immediate: Bool = false) {
        guard let snapshot = original, active || immediate else { return }
        active = false
        if immediate {
            generation += 1; scale = 1
            if layer.set(snapshot, volume: snapshot.volume) { original = nil; changed(nil) }
            else { later(1) { [weak self] in self?.end(immediate: true) } }
            return
        }
        ramp(to: 1)
    }
    private func ramp(to target: Float32) {
        guard original != nil else { return }
        generation += 1; let mine = generation, from = scale, steps = 6
        for step in 1...steps {
            later(Double(step) * 0.025) { [weak self] in
                guard let self, generation == mine, let original else { return }
                scale = from + (target - from) * Float32(step) / Float32(steps)
                let restored = layer.set(original, volume: original.volume * scale)
                if step == steps, target == 1, restored { self.original = nil; changed(nil) }
                if step == steps, target == 1, !restored { later(1) { [weak self] in self?.end(immediate: true) } }
            }
        }
    }
    deinit { end(immediate: true) }
}

enum AudioRecovery {
    static var marker: URL?
    static let prefix = ".rabik-audio-"
    static var folder: URL { URL(fileURLWithPath: (Prefs.path as NSString).deletingLastPathComponent, isDirectory: true) }
    static func read(_ url: URL) -> AudioVolumeSnapshot? { try? JSONDecoder().decode(AudioVolumeSnapshot.self, from: Data(contentsOf: url)) }
    static func restore(_ url: URL) {
        guard let snapshot = read(url), CoreAudioVolume().set(snapshot, volume: snapshot.volume) else { return }
        try? FileManager.default.removeItem(at: url)
    }
    static func changed(_ snapshot: AudioVolumeSnapshot?) {
        if let snapshot {
            try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let url = folder.appendingPathComponent(prefix + UUID().uuidString + ".json")
            guard let data = try? JSONEncoder().encode(snapshot), (try? data.write(to: url, options: .atomic)) != nil else { return }
            marker = url
            let watcher = Process(); watcher.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
            watcher.arguments = ["--restore-audio", url.path, String(snapshot.owner)]; try? watcher.run()
        } else if let marker {
            try? FileManager.default.removeItem(at: marker); self.marker = nil
        }
    }
    static func start() {
        let args = CommandLine.arguments
        if args.count == 4, args[1] == "--restore-audio", let owner = Int32(args[3]) {
            let url = URL(fileURLWithPath: args[2])
            while FileManager.default.fileExists(atPath: url.path), kill(owner, 0) == 0 { usleep(100_000) }
            restore(url); exit(0)
        }
        recoverStale()
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in recoverStale() }
    }
    static func recoverStale() {
        for name in (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? [] where name.hasPrefix(prefix) {
            let url = folder.appendingPathComponent(name)
            if let snapshot = read(url), kill(snapshot.owner, 0) != 0 { restore(url) }
        }
    }
}
