// Routines that wake the Mac. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// launchd writes one ID when a routine is due. A file event wakes the existing agent supervisor; no timer polls.
final class RoutineWake {
    let path = (Prefs.path as NSString).deletingLastPathComponent + "/routine-queue.jsonl"
    var source: DispatchSourceFileSystemObject?, draining = false, pending = false
    init() {
        try? FileManager.default.createDirectory(atPath: (path as NSString).deletingLastPathComponent, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath:path) { FileManager.default.createFile(atPath:path, contents:Data(), attributes:[.posixPermissions:0o600]) }
        let fd = open(path, O_EVTONLY)
        guard fd >= 0 else { return }
        source = DispatchSource.makeFileSystemObjectSource(fileDescriptor:fd, eventMask:[.write,.rename,.delete], queue:.main)
        source?.setEventHandler { [weak self] in self?.changed() }
        source?.setCancelHandler { close(fd) }
        source?.resume()
        DispatchQueue.main.async { [weak self] in self?.changed() }
    }
    func changed() { pending = true; drain() }
    func drain() {
        guard !draining else { return }
        draining = true; pending = false
        DispatchQueue.global().async { [weak self] in
            let p = py(["--routine-pop"]), out = Pipe(); p.standardOutput = out
            try? p.run(); let data = out.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
            let ids = (try? JSONSerialization.jsonObject(with:data)) as? [String] ?? []
            DispatchQueue.main.async {
                guard let self else { return }
                ids.forEach { agentsUI.send(["action":"routine","id":$0]) }
                self.draining = false
                if self.pending { self.drain() }
            }
        }
    }
}
