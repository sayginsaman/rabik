// The speech recognizers an ask listens with. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

final class SpeechInputs: @unchecked Sendable {
    private let lock = NSLock()
    private var feeds: [UUID: AsyncStream<AnalyzerInput>.Continuation] = [:]
    func add(_ feed: AsyncStream<AnalyzerInput>.Continuation) -> UUID {
        let id = UUID(); lock.lock(); feeds[id] = feed; lock.unlock(); return id
    }
    func yield(_ input: AnalyzerInput) {
        lock.lock(); let current = Array(feeds.values); lock.unlock()
        current.forEach { $0.yield(input) }
    }
    func finish(_ id: UUID) {
        lock.lock(); let feed = feeds.removeValue(forKey: id); lock.unlock(); feed?.finish()
    }
    func finishAll() {
        lock.lock(); let current = Array(feeds.values); feeds.removeAll(); lock.unlock()
        current.forEach { $0.finish() }
    }
}
