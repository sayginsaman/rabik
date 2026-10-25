// The daily recap. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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


// The daily recap (brain/recap.py). Its launchd job's queue entry, Rabik starting and the Mac waking each ask the brain whether the
// evening recap is due; the brain makes it at most once a day, and only a day with something in it.
final class Recap {
    var checking = false
    init() {
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in self?.catchUp() }
    }
    func catchUp() {
        guard !checking else { return }
        checking = true
        DispatchQueue.global().async { [weak self] in
            let p = py(["--recap", "catch-up"]), out = Pipe(); p.standardOutput = out; p.standardError = FileHandle.nullDevice
            let made = (try? JSONSerialization.jsonObject(with: runToEnd(p, out))) as? [String: Any] ?? [:]
            DispatchQueue.main.async {
                guard let self else { return }
                self.checking = false
                if made["day"] != nil && made["empty"] == nil { self.ready(made) }
            }
        }
    }
    func sync() {   // Settings changed it: the job follows, and a recap already due shows now
        DispatchQueue.global().async { [weak self] in
            let p = py(["--recap", "schedule"]), out = Pipe(); p.standardOutput = out; p.standardError = FileHandle.nullDevice
            _ = runToEnd(p, out)
            DispatchQueue.main.async { self?.catchUp() }
        }
    }
    func ready(_ recap: [String: Any]) {}
}
