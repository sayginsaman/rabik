// Meeting Copilot: call audio, the live brief and notes, and the archive. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// Meeting audio stays on-device; the journal stores text, never audio.
final class MeetingArchive {
    let id: String, folder: String
    let handle: FileHandle
    private let queue = DispatchQueue(label: "rabik.meeting.archive")
    static let writes = DispatchGroup()
    init(title: String, app: String, started: Date) throws {
        id = UUID().uuidString
        let root = (Prefs.path as NSString).deletingLastPathComponent + "/meetings"
        folder = root + "/" + id
        let fm = FileManager.default
        if (try? fm.attributesOfItem(atPath: root)[.type] as? FileAttributeType) == .typeSymbolicLink { throw CocoaError(.fileWriteNoPermission) }
        try fm.createDirectory(atPath: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: root)
        try fm.createDirectory(atPath: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let metadata: [String: Any] = ["title": title, "app": app, "started": started.timeIntervalSince1970, "version": 1]
        let data = try JSONSerialization.data(withJSONObject: metadata, options: [.sortedKeys])
        guard fm.createFile(atPath: folder + "/metadata.json", contents: data, attributes: [.posixPermissions: 0o600]), fm.createFile(atPath: folder + "/events.jsonl", contents: nil, attributes: [.posixPermissions: 0o600]) else { throw CocoaError(.fileWriteUnknown) }
        let fd = Darwin.open(folder + "/events.jsonl", O_WRONLY | O_APPEND | O_NOFOLLOW)
        guard fd >= 0 else { throw CocoaError(.fileWriteUnknown) }; handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
    }
    func append(_ events: [[String: Any]], completion: @escaping (Error?) -> Void) {
        queue.async(group: Self.writes) { [self] in
            do {
                var data = Data()
                for event in events { data.append(try JSONSerialization.data(withJSONObject: event, options: [.sortedKeys])); data.append(10) }
                try handle.write(contentsOf: data); try handle.synchronize()
                DispatchQueue.main.async { completion(nil) }
            } catch { DispatchQueue.main.async { completion(error) } }
        }
    }
    static func export(_ text: String, to url: URL) throws {
        let temp = url.deletingLastPathComponent().appendingPathComponent(".rabik-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: temp) }
        guard FileManager.default.createFile(atPath: temp.path, contents: Data(text.utf8), attributes: [.posixPermissions: 0o600]), Darwin.rename(temp.path, url.path) == 0 else { throw CocoaError(.fileWriteUnknown) }
    }
    deinit { try? handle.close() }
}

final class MeetingAudio: NSObject, SCStreamOutput, SCStreamDelegate {
    var stream: SCStream?, feed: AsyncStream<AnalyzerInput>.Continuation?, micFeed: AsyncStream<AnalyzerInput>.Continuation?
    var format: AVAudioFormat?, converter: AVAudioConverter?, natural: AVAudioFormat?
    var micConverter: AVAudioConverter?, micNatural: AVAudioFormat?
    var onError: ((Error) -> Void)?, onLevel: ((Float) -> Void)?
    var levelAt = Date.distantPast, level: Float = 0, micLevel: Float = 0
    var samples = 0, peak: Float = 0
    let queue = DispatchQueue(label: "meeting.audio")
    func start(_ format: AVAudioFormat?, _ feed: AsyncStream<AnalyzerInput>.Continuation?, _ micFeed: AsyncStream<AnalyzerInput>.Continuation?, microphoneID: String? = nil) async throws {
        self.format = format; self.feed = feed; self.micFeed = micFeed
        let all = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = all.displays.first else { throw NSError(domain: "Meeting", code: 1) }
        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true; cfg.excludesCurrentProcessAudio = true; cfg.captureMicrophone = micFeed != nil
        if micFeed != nil { cfg.microphoneCaptureDeviceID = microphoneID }
        cfg.sampleRate = 48000; cfg.channelCount = 2
        cfg.width = 2; cfg.height = 2; cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1); cfg.showsCursor = false
        let s = SCStream(filter: SCContentFilter(display: display, excludingWindows: []), configuration: cfg, delegate: self)
        stream = s
        try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        if micFeed != nil { try s.addStreamOutput(self, type: .microphone, sampleHandlerQueue: queue) }
        try await s.startCapture()
    }
    func stop() async {
        let s = stream; stream = nil
        try? await s?.stopCapture()
        queue.sync { feed?.finish(); micFeed?.finish(); feed = nil; micFeed = nil; converter = nil; natural = nil; micConverter = nil; micNatural = nil }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) { onError?(error) }
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio || type == .microphone, sample.isValid, let desc = sample.formatDescription,
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc), let source = AVAudioFormat(streamDescription: asbd),
              let buffer = AVAudioPCMBuffer(pcmFormat: source, frameCapacity: AVAudioFrameCount(sample.numSamples)) else { return }
        buffer.frameLength = buffer.frameCapacity
        guard CMSampleBufferCopyPCMDataIntoAudioBufferList(sample, at: 0, frameCount: Int32(sample.numSamples), into: buffer.mutableAudioBufferList) == noErr else { return }
        samples += Int(buffer.frameLength)
        var amplitude: Float = 0
        if let channel = buffer.floatChannelData?[0] { for i in 0..<Int(buffer.frameLength) { amplitude = max(amplitude, abs(channel[i])) } }
        else if let channel = buffer.int16ChannelData?[0] { for i in 0..<Int(buffer.frameLength) { amplitude = max(amplitude, Float(abs(Int(channel[i]))) / 32768) } }
        peak = max(peak, amplitude); level = max(level * 0.75, amplitude); if type == .microphone { micLevel = max(micLevel * 0.75, amplitude) }
        if Date().timeIntervalSince(levelAt) >= 0.1 { levelAt = Date(); onLevel?(level) }
        let mic = type == .microphone
        guard let feed = mic ? micFeed : feed else { return }
        let want = format ?? source
        if mic {
            if source != micNatural { micNatural = source; micConverter = source == want ? nil : AVAudioConverter(from: source, to: want) }
        } else if source != natural { natural = source; converter = source == want ? nil : AVAudioConverter(from: source, to: want) }
        let converter = mic ? micConverter : converter
        if source == want { feed.yield(AnalyzerInput(buffer: buffer)); return }
        guard let converter, let out = AVAudioPCMBuffer(pcmFormat: want, frameCapacity: AVAudioFrameCount(Double(buffer.frameLength) * want.sampleRate / source.sampleRate) + 1) else { return }
        var given = false, error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if given { status.pointee = .noDataNow; return nil }; given = true; status.pointee = .haveData; return buffer
        }
        if error == nil && out.frameLength > 0 { feed.yield(AnalyzerInput(buffer: out)) }
    }
}

// Geometry stays in Cocoa coordinates, including displays left of or above the main one.
enum MeetingFrame {
    static func clamp(_ frame: NSRect, _ bounds: NSRect) -> NSRect {
        var f = frame; f.size.width = min(f.width, bounds.width); f.size.height = min(f.height, bounds.height)
        f.origin.x = min(max(f.minX, bounds.minX), bounds.maxX - f.width)
        f.origin.y = min(max(f.minY, bounds.minY), bounds.maxY - f.height)
        return f
    }
    // The same frame on another display: the same distance from the chosen side and from the top or bottom.
    static func follow(_ f: NSRect, _ from: NSRect, _ to: NSRect, right: Bool, top: Bool) -> NSRect {
        var g = f
        g.origin.x = right ? to.maxX - (from.maxX - f.maxX) - f.width : to.minX + (f.minX - from.minX)
        g.origin.y = top ? to.maxY - (from.maxY - f.maxY) - f.height : to.minY + (f.minY - from.minY)
        return g
    }
    static func initial(_ saved: [Double]?, _ bounds: NSRect) -> NSRect {
        let fallback = NSRect(x: bounds.minX + 12, y: bounds.maxY - min(470, bounds.height - 24) - 12, width: min(340, bounds.width - 24), height: min(470, bounds.height - 24))
        guard let s = saved, s.count == 4, s.allSatisfy({ $0.isFinite }), s[2] >= 44, s[3] >= 44 else { return fallback }
        let frame = NSRect(x: s[0], y: s[1], width: s[2], height: s[3])
        guard bounds.contains(frame) else { return fallback }
        return frame
    }
    static func key(_ screen: NSScreen) -> String { String(describing: screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] ?? "main") }
}

final class MeetingWebView: WKWebView {
    var onFiles: (([String]) -> Void)?
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation { .copy }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        guard let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self]) as? [URL] else { return false }
        onFiles?(urls.map(\.path)); return true
    }
}

final class MeetingCopilot: NSObject, WKScriptMessageHandler {
    var panel: KeyPanel?, web: WKWebView?, audio: MeetingAudio?, analyzer: SpeechAnalyzer?, reading: Task<Void, Never>?, starting: Task<Void, Never>?
    var translator: TranslationSession?, translationFailed = false   // Translate the call (MeetingSpeech)
    var people: [String] = [], named: [String: String] = [:], sinceGuess = 0, lastGuess = Date.distantPast, guessing: Process?   // speaker names: callPeople, guessSpeakers
    var other: String? { room || people.count != 1 ? nil : people[0] }   // a 1:1 on the calendar: who "Them" is
    var micAnalyzer: SpeechAnalyzer?, micReading: Task<Void, Never>?, analyzing: Task<Void, Never>?, micAnalyzing: Task<Void, Never>?, stopping: Task<Void, Never>?
    var micPending = "", micPartial = "", micSettle: DispatchWorkItem?, elapsed: TimeInterval = 0
    var partialQuestion: Int?, micPartialQuestion: Int?
    var voice = false, voiceText = "", voicePartial = "", voiceTail = Date.distantPast   // talking to Rabik: your mic goes to the ask box, not the transcript
    var running = false, generation = 0, brief = "", name = "", began = Date(), transcript: [[String: Any]] = []
    var process: Process?, demoProcess: Process?, finishing: Process?, queue: [[String: Any]] = [], timer: Timer?, pending = "", partial = "", settle: DispatchWorkItem?
    var answerProcess: Process?, answerInput: Pipe?, answerOutput: Pipe?, answerTimes: [Int: [String: Double]] = [:], answerQuestion = ""
    var demo = false, loaded = false, briefEdited = false, gathering = false, prepWaiting = false, serial = 0, answering: Int?, nudge: [String: Any]?
    var calendarContext = meetingCalendarContext
    var expanded = NSSize(width: 340, height: 650), minimized = false, resizing = false
    var pendingBrief: String?
    var agentPrep: [String:Any]?
    var moveMonitor: Any?, screenObserver: NSObjectProtocol?, mouseDown: NSPoint?, dragOrigin: NSRect?, dragging = false
    var archive: MeetingArchive?, archiveEnded = false, meetingTitle = "", callApp = "Call"
    var room: Bool { callApp == "In person" }   // no call: the mic hears everyone, so its questions get answers too
    var style: String {   // the answer style picked on the prep screen, read per answer so Settings edits apply mid-call
        let pick = Prefs.str("meetingStyle")
        if pick == "Custom…" { return Prefs.str("meetingCustom") }
        return (Prefs.d["meetingStyles"] as? [[String: Any]])?.first { $0["name"] as? String == pick }?["text"] as? String ?? ""
    }
    var measured: [Int: Double] = [:], demoEnds: [Double] = []
    func js(_ call: String, _ value: Any = [:]) {
        callJS(web, "meeting." + call, [value])
    }
    func open(demo: Bool = false, nudge: [String: Any]? = nil) {
        guard Prefs.bool("meeting"), !Prefs.bool("paused") else { return }
        if let panel {
            guard nudge == nil else { return }
            if self.nudge != nil { self.nudge = nil; panel.contentView?.layer?.cornerRadius = 18; if loaded { js("prep") } }   // asked for while the call card shows: open prep
            panel.orderFrontRegardless(); focus(); return
        }
        self.demo = demo; self.nudge = nudge; minimized = false; loaded = false; generation += 1; transcript = []; brief = ""; pending = ""; partial = ""; micPending = ""; micPartial = ""; elapsed = 0; serial = 0
        archive = nil; archiveEnded = false; meetingTitle = nudge?["context"] as? String == "" ? "" : nudge?["title"] as? String ?? ""; callApp = nudge?["app"] as? String ?? "Call"; people = []; named = [:]; sinceGuess = 0
        let config = (Prefs.path as NSString).deletingLastPathComponent
        name = profileName(config + "/me.json")
        let frames = Prefs.d["meetingFrames"] as? [String: [Double]] ?? [:]
        let screen = NSScreen.screens.first { MeetingFrame.key($0) == Prefs.str("meetingDisplay") } ?? mouseScreen
        let frame = MeetingFrame.initial(frames[MeetingFrame.key(screen)], screen.visibleFrame)
        let p = KeyPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        if let saved = (Prefs.d["meetingSizes"] as? [String: [Double]])?[MeetingFrame.key(screen)], saved.count == 2, saved.allSatisfy({ $0.isFinite && $0 > 0 }) { expanded = NSSize(width: max(280, saved[0]), height: max(380, saved[1])) }
        p.acceptsMouseMovedEvents = true
        p.level = .statusBar; p.isOpaque = false; p.backgroundColor = .clear; p.hasShadow = true; p.hidesOnDeactivate = false
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]; applySharing(p)
        let cfg = WKWebViewConfiguration(); cfg.userContentController.add(self, name: "meeting")
        let v = MeetingWebView(frame: NSRect(origin: .zero, size: p.frame.size), configuration: cfg)
        v.onFiles = { [weak self] paths in self?.material(paths) }; v.registerForDraggedTypes([.fileURL])
        v.setValue(false, forKey: "drawsBackground"); v.autoresizingMask = [.width, .height]
        let bg = NSVisualEffectView(frame: v.frame); bg.material = .hudWindow; bg.state = .active; bg.appearance = NSAppearance(named: .darkAqua)
        bg.wantsLayer = true; bg.layer?.cornerRadius = 18; bg.layer?.masksToBounds = true; bg.autoresizingMask = [.width, .height]; bg.addSubview(v)
        let tracker = Tracker(frame: v.frame); tracker.autoresizingMask = [.width, .height]
        tracker.onMove = { [weak self, weak v] point in
            guard let v else { return }; self?.js("hover", [point.x, v.bounds.height - point.y])
        }
        tracker.onExit = { [weak self] in self?.js("hover", []) }
        bg.addSubview(tracker)
        p.contentView = bg; panel = p; web = v
        moveMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .leftMouseDragged, .leftMouseUp]) { [weak self] event in
            guard let self, event.window === panel else { return event }
            if event.type == .leftMouseDown { mouseDown = panel?.convertPoint(toScreen: event.locationInWindow); dragOrigin = nil; dragging = false }
            if event.type == .leftMouseDragged, let origin = dragOrigin, let down = mouseDown {
                let point = NSEvent.mouseLocation
                guard hypot(point.x - down.x, point.y - down.y) > 3 else { return event }
                var f = origin; f.origin.x += point.x - down.x; f.origin.y += point.y - down.y
                let target = NSScreen.screens.first { $0.frame.contains(point) } ?? panel?.screen ?? NSScreen.main!
                panel?.setFrame(MeetingFrame.clamp(f, target.visibleFrame), display: true)
                dragging = true; return nil
            }
            if event.type == .leftMouseUp { if dragging { rememberFrame() }; dragOrigin = nil; mouseDown = nil; let moved = dragging; dragging = false; if moved { return nil } }
            return event
        }
        screenObserver = NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self, let panel, let screen = panel.screen ?? NSScreen.main else { return }
            panel.setFrame(MeetingFrame.clamp(panel.frame, screen.visibleFrame), display: true)
        }
        if nudge != nil { p.setFrame(NSRect(x: p.frame.minX, y: p.frame.maxY - 52, width: 52, height: 52), display: false); bg.layer?.cornerRadius = 26 }   // a blob in the corner; size() grows it into the card
        loadPage(v, "meeting.html")
        p.orderFrontRegardless()
    }
    func ready() {
        guard !loaded else { return }; loaded = true
        js("motion", NSWorkspace.shared.accessibilityDisplayShouldReduceMotion)
        js("privacy", Prefs.bool("meetingSave"))
        js("calendar", [.fullAccess, .notDetermined].contains(EKEventStore.authorizationStatus(for: .event)))   // not asked yet: Fill in for me asks
        js("styles", ["list": Prefs.d["meetingStyles"] ?? [], "pick": Prefs.str("meetingStyle"), "custom": Prefs.str("meetingCustom")])
        js("width", min(340, ((panel?.screen ?? NSScreen.main)?.visibleFrame.width ?? 364) - 24))
        js("savedPrep", Prefs.str("meetingPrep"))
        if agentPrep == nil, EKEventStore.authorizationStatus(for:.event) == .fullAccess, let event = currentMeetingEvent(calendar), let id = event["id"] as? String {
            agentPrep = (Prefs.d["meetingAgentPreps"] as? [String:[String:Any]])?[id]
        }
        if demo {
            worker("--meeting-demo-brief", [:]) { [weak self] result in
                if result["error"] != nil { self?.js("error", "Could not load demo brief"); self?.js("prep") }
                else { self?.js("demoPrep", result) }
                self?.focus()
            }
        } else if let nudge { panel?.contentView?.layer?.cornerRadius = 18; js("nudge", nudge) }   // a calendar reminder: shown, never steals focus
        else { js("mode", callAppsOnMic().isEmpty ? "room" : "call"); js("prep"); focus() }
        if let agentPrep { showAgentPrep(agentPrep) }
    }
    func rememberFrame() {
        guard let panel, let screen = panel.screen else { return }
        let key = MeetingFrame.key(screen), f = panel.frame
        var frames = Prefs.d["meetingFrames"] as? [String: [Double]] ?? [:]
        frames[key] = [f.minX, f.minY, f.width, f.height]
        var sizes = Prefs.d["meetingSizes"] as? [String: [Double]] ?? [:]; sizes[key] = [expanded.width, expanded.height]
        Prefs.set("meetingSizes", sizes)
        Prefs.set("meetingFrames", frames); Prefs.set("meetingDisplay", key)
    }
    func resetFrame() {
        guard let panel, let screen = panel.screen ?? NSScreen.main else { return }
        var f = panel.frame; f.origin = NSPoint(x: screen.visibleFrame.minX + 12, y: screen.visibleFrame.maxY - f.height - 12)
        panel.setFrame(MeetingFrame.clamp(f, screen.visibleFrame), display: true); rememberFrame()
    }
    // The page asks for its height (0 = the full live view); the top edge stays put.
    func size(_ h: Double, reveal: Int? = nil) {
        guard let panel, let screen = panel.screen ?? NSScreen.main else { return }
        let bounds = screen.visibleFrame.insetBy(dx: 12, dy: 12)
        let top = min(max(panel.frame.maxY, bounds.minY), bounds.maxY)
        let most = max(1, top - bounds.minY)
        let want = h <= 0 ? min(expanded.height, most) : min(most, max(minimized ? 44 : 80, h))
        var f = panel.frame; f.origin.y = top - want; f.size.height = want
        f.size.width = min(minimized ? 116 : expanded.width, bounds.width); f.origin.x = panel.frame.minX   // expand from the same top-left corner as the assistant
        f.origin.x = min(max(f.minX, bounds.minX), bounds.maxX - f.width)
        f.origin.y = min(max(f.minY, bounds.minY), bounds.maxY - f.height)
        guard f != panel.frame else { if let reveal { js("settled", reveal) }; return }
        if let reveal, !resizing, !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            let g = generation
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.22
                panel.animator().setFrame(f, display: true)
            } completionHandler: { [weak self] in
                guard let self, generation == g else { return }; js("settled", reveal)
            }
        } else {
            panel.setFrame(f, display: true, animate: !resizing && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion)
            if let reveal { js("settled", reveal) }
        }
    }
    func resize(_ width: Double, _ height: Double) {
        guard running, !minimized, let screen = panel?.screen ?? NSScreen.main else { return }
        let bounds = screen.visibleFrame.insetBy(dx: 12, dy: 12)
        expanded = NSSize(width: min(bounds.width, max(280, width)), height: min(bounds.height, max(380, height)))
        resizing = true; size(0); resizing = false
    }
    func compact(_ on: Bool) {
        guard running else { return }; minimized = on; panel?.contentView?.layer?.cornerRadius = on ? 22 : 18; js("compact", on)
        if !on { focus() }
    }
    func focus() { panel?.makeKey(); panel?.makeFirstResponder(web); js("focus") }
    func saveEvent(_ event: [String: Any]) {
        saveEvents([event])
    }
    func saveEvents(_ events: [[String: Any]]) {
        guard Prefs.bool("meetingSave"), let archive else { return }
        archive.append(events) { [weak self] error in
            guard let self, error != nil, self.archive === archive else { return }
            self.archive = nil; js("saving", false); js("error", "Transcript could not save. Check available disk space.")
        }
    }
    func beginArchive() {
        guard Prefs.bool("meetingSave"), archive == nil else { js("saving", archive != nil); return }
        do {
            let date = DateFormatter(); date.dateStyle = .medium; date.timeStyle = .short
            archive = try MeetingArchive(title: meetingTitle.isEmpty ? callApp + " · " + date.string(from: began) : meetingTitle, app: callApp, started: began)
            archiveEnded = false; saveEvent(["kind": "notes", "text": brief]); js("saving", true)
        } catch { js("saving", false); js("error", "Could not save this transcript. Check available disk space.") }
    }
    func finishArchive(summarize: Bool = true) {
        guard let archive, !archiveEnded else { return }
        archiveEnded = true
        archive.append([["kind": "ended", "at": Date().timeIntervalSince1970, "duration": elapsed]]) { [weak self] error in
            guard let self, self.archive === archive else { return }
            if error != nil { self.archive = nil; archiveEnded = false; js("saving", false); js("error", "Transcript could not save. Check available disk space."); return }
            guard summarize, archiveEnded, !running else { return }
            let id = archive.id
            let p = py(["--meetings"]), input = Pipe(), output = Pipe(); p.standardInput = input; p.standardOutput = output
            fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
            do { try p.run() } catch { return }; finishing = p
            DispatchQueue.global().async { [weak self] in
                do { try input.fileHandleForWriting.write(contentsOf: JSONSerialization.data(withJSONObject: ["action": "finish", "id": id])); try input.fileHandleForWriting.close() } catch { p.terminate(); return }
                let data = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
                let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
                DispatchQueue.main.async { [weak self] in
                    guard let self, finishing === p else { return }; finishing = nil
                    guard archive.id == self.archive?.id, !running else { return }
                    if let m = result["meeting"] as? [String: Any] { js("recap", m) }
                }
            }
        }
    }
    func savingChanged(_ on: Bool) {
        if on && running { beginArchive() }
        if !on { finishing?.terminate(); finishing = nil; elapsed = running ? Date().timeIntervalSince(began) : elapsed; finishArchive(summarize:false); archive = nil; js("saving", false) }
    }
    func start(_ context: String) {
        guard loaded, !running, Prefs.bool("meeting"), !Prefs.bool("paused") else { return }
        cancelWork(); brief = String(context.prefix(meetingBriefLimit)); briefEdited = false; running = true; began = Date().addingTimeInterval(-elapsed); nudge = nil; app.close(clear: false); app.shortcutDown = false
        if callApp == "Call" { callApp = demo ? "Demo" : callAppsOnMic().sorted().first ?? "Call" }
        people = demo ? [] : callPeople()
        beginArchive()
        if archiveEnded { saveEvent(["kind": "resumed", "duration": elapsed]); archiveEnded = false }
        js("listen"); bar.paint()
        warmAnswer()
        // Short notes are the context as-is (no AI call); long notes or a link get boiled down while it listens.
        if context.count > meetingBriefLimit || context.range(of: #"^https?://\S+$"#, options: .regularExpression) != nil { prepare(context) }
        let g = generation
        starting = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                await stopping?.value
                guard running, generation == g, !Task.isCancelled else { return }
                let micAllowed = demo ? true : await AVCaptureDevice.requestAccess(for: .audio)
                guard running, generation == g, !Task.isCancelled else { return }
                guard micAllowed else { stop(); js("error", "Allow Microphone access for Rabik in System Settings"); return }
                let locale = await MeetingSpeech.locale()   // Settings → Meetings → Language
                let (mic, micWords) = await MeetingSpeech.transcriber(locale), (tr, words) = await MeetingSpeech.transcriber(locale)
                translator = MeetingSpeech.translator(from: locale); translationFailed = false
                if let request = try await AssetInventory.assetInstallationRequest(supporting: [tr]) { try await request.downloadAndInstall() }
                guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [tr]) else {
                    if running && generation == g { stop(); js("error", "Speech recognition is unavailable. Resume to try again.") }; return
                }
                guard running, generation == g, !Task.isCancelled else { return }
                let (stream, feed) = AsyncStream<AnalyzerInput>.makeStream()
                let (micStream, micFeed) = AsyncStream<AnalyzerInput>.makeStream()
                let an = SpeechAnalyzer(modules: [tr]); analyzer = an
                let micAn = SpeechAnalyzer(modules: [mic]); micAnalyzer = micAn
                let context = AnalysisContext(); context.contextualStrings[.general] = [name, "Rabik"].filter { !$0.isEmpty }
                try await an.setContext(context)
                try await micAn.setContext(context)
                guard running, generation == g, !Task.isCancelled else { return }
                reading = Task { [weak self] in
                    do { for try await (piece, final) in words {
                        await MainActor.run { if self?.generation == g && self?.running == true { self?.speech(piece, final: final) } }
                    } } catch { await MainActor.run { if self?.running == true && self?.generation == g { self?.stop(); self?.js("error", "Speech stopped") } } }
                }
                micReading = Task { [weak self] in
                    do { for try await (piece, final) in micWords {
                        await MainActor.run { if self?.generation == g && self?.running == true { self?.speech(piece, final: final, mic: true) } }
                    } } catch { await MainActor.run { if self?.running == true && self?.generation == g { self?.stop(); self?.js("error", "Microphone transcription stopped. Resume to try again.") } } }
                }
                analyzing = Task { [weak self] in
                    do { try await an.start(inputSequence: stream) }
                    catch { if self?.generation == g && self?.running == true { self?.stop(); self?.js("error", "Call transcription stopped. Resume to try again.") } }
                }
                micAnalyzing = Task { [weak self] in
                    do { try await micAn.start(inputSequence: micStream) }
                    catch { if self?.generation == g && self?.running == true { self?.stop(); self?.js("error", "Microphone transcription stopped. Resume to try again.") } }
                }
                let capture = MeetingAudio(); audio = capture
                capture.onLevel = { [weak self, weak capture] level in let mine = capture?.micLevel ?? 0; DispatchQueue.main.async { [weak self] in
                    guard let self, generation == g, running else { return }
                    if voice { js("level", mine) } else if minimized { js("level", level) }   // voice waves follow only your mic
                } }
                capture.onError = { [weak self] _ in DispatchQueue.main.async { if self?.generation == g && self?.running == true { self?.stop(); self?.js("error", "Audio stopped") } } }
                try await capture.start(format, feed, demo ? nil : micFeed, microphoneID: demo ? nil : listenMic()?.uid)
                if !running || generation != g || Task.isCancelled { await capture.stop(); return }
                Prefs.set("meetingPrep", "")
                js("capturing")
                if demo { playDemo() }
            } catch { if running && generation == g { stop(); js("error", "Allow Screen Recording in Settings") } }
        }
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self else { return }; let seconds = Int(Date().timeIntervalSince(began)); js("clock", seconds)
            if seconds % 2 == 0 {
                saveEvents([["kind": "partial", "seconds": seconds, "at": Date().timeIntervalSince1970, "them": pending + " " + partial, "you": micPending + " " + micPartial],
                            ["kind": "checkpoint", "duration": seconds]])
            }
        }
    }
    func speech(_ piece: String, final: Bool, mic: Bool = false) {
        guard running else { return }
        if mic && voice {
            if final { voiceText += " " + piece; voicePartial = "" } else { voicePartial = piece }
            return js("heard", (voiceText + " " + voicePartial).trimmingCharacters(in: .whitespaces))
        }
        if mic && Date() < voiceTail { return }   // the last words of a voice ask finishing; already in the ask
        if mic { micPartial = final ? "" : piece } else { partial = final ? "" : piece }
        js("partial", ["mic": mic && !room, "text": final ? "" : piece])
        let clearlyQuestion = !final && (!mic || room) && piece.trimmingCharacters(in: .whitespacesAndNewlines).hasSuffix("?")
        if clearlyQuestion && (mic ? micPartialQuestion : partialQuestion) == nil && Prefs.str("meetingAuto") != "ask" {
            serial += 1
            if mic { micPartialQuestion = serial } else { partialQuestion = serial }
            let now = Date().timeIntervalSince1970
            let askedBy = room ? "Someone in the room" : other ?? (callApp == "Call" ? "Someone else" : "Someone on " + callApp)
            let row: [String: Any] = ["id": serial, "text": piece, "seconds": Int(Date().timeIntervalSince(began)), "speaker": askedBy]
            js("question", row.merging(["auto": true, "heard": true]) { $1 })
            enqueue(serial, piece, best: Prefs.str("meetingAuto") == "always", at: now, detectedAt: now)
        }
        if final { heard(piece, mic: mic) }
    }
    func heard(_ piece: String, mic: Bool = false) {
        if mic { micPending += " " + piece; micSettle?.cancel() } else { pending += " " + piece; settle?.cancel() }
        if (mic ? micPending : pending).trimmingCharacters(in: .whitespacesAndNewlines).last.map({ "?.!".contains($0) }) == true { flush(mic: mic) }
        else {
            let item = DispatchWorkItem { [weak self] in self?.flush(mic: mic) }
            if mic { micSettle = item } else { settle = item }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2, execute: item)
        }
    }
    func flush(answer: Bool = true, mic: Bool = false) {
        let text = (mic ? micPending : pending).trimmingCharacters(in: .whitespacesAndNewlines)
        if mic { micPending = "" } else { pending = "" }
        guard running, !text.isEmpty else { return }
        let at = Date().timeIntervalSince1970, you = mic && !room
        let candidate = mic ? micPartialQuestion : partialQuestion
        if mic { micPartialQuestion = nil } else { partialQuestion = nil }
        if candidate == nil { serial += 1 }
        let id = candidate ?? serial, speaker = you ? "You" : room ? "Room" : other ?? (callApp == "Call" ? "Them" : callApp)
        let askedBy = you ? "You" : room ? "Someone in the room" : other ?? (callApp == "Call" ? "Someone else" : "Someone on " + callApp)
        transcript.append(["id": id, "at": at, "text": text, "seconds": Int(Date().timeIntervalSince(began)), "mic": you])
        saveEvent(["kind": "transcript", "id": id, "at": at, "text": text, "seconds": Int(Date().timeIntervalSince(began)), "mic": you, "speaker": speaker])
        var row: [String: Any] = ["id": id, "text": text, "seconds": Int(Date().timeIntervalSince(began)), "mic": you, "speaker": askedBy]
        if !you, let other { row["name"] = other }
        js("line", row)
        if !you { sinceGuess += 1; guessSpeakers() }
        if !you, let session = translator, !translationFailed {   // the other side, in the Mac's language, under the line
            Task { @MainActor [weak self] in
                do { let done = try await session.translate(text); self?.js("translated", ["id": id, "text": done.targetText]) }
                catch { guard self?.translationFailed == false else { return }; self?.translationFailed = true
                    self?.js("translated", ["id": id, "error": "Translation needs both languages: System Settings → General → Language & Region → Translation Languages."]) }
            }
        }
        if answer && !you {
            if let index = queue.firstIndex(where: { $0["id"] as? Int == id }) {
                queue[index]["question"] = text; queue[index]["transcript"] = transcript; queue[index]["finalAt"] = at
            }
            let automatic = Prefs.str("meetingAuto") != "ask", question = text.hasSuffix("?")
            if question { js("question", row.merging(["auto": automatic, "heard": true]) { $1 }) }
            if candidate == nil && automatic && question { enqueue(id, text, best: Prefs.str("meetingAuto") == "always", at: at, detectedAt: Date().timeIntervalSince1970) }
        }
    }
    func enqueue(_ id: Int, _ question: String, best: Bool, at: Double? = nil, image: String? = nil, detectedAt: Double? = nil) {
        guard running, !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        if answering == id || queue.contains(where: { $0["id"] as? Int == id }) { return }
        let now = Date().timeIntervalSince1970
        var data: [String: Any] = ["id": id, "transcript": transcript, "now": now, "question": question, "best": best, "at": at ?? now,
                                   "finalAt": at ?? now, "detectedAt": detectedAt ?? now]
        if let image { data["image"] = image }
        queue.append(data); next()
    }
    func prepare(_ context: String) { pendingBrief = String(context.prefix(20000)); briefEdited = false; next() }
    func acceptAgent(_ row:[String:Any]) {
        let event = row["meetingEvent"] as? [String:Any] ?? [:]
        let key = event["id"] as? String ?? (event["title"] as? String ?? "") + "@" + (event["time"] as? String ?? "")
        var preps = Prefs.d["meetingAgentPreps"] as? [String:[String:Any]] ?? [:]
        preps[key] = row; Prefs.set("meetingAgentPreps",preps)
        if EKEventStore.authorizationStatus(for:.event) == .fullAccess, currentMeetingEvent(calendar)?["id"] as? String == event["id"] as? String {
            agentPrep = row; if panel != nil, !running { showAgentPrep(row) }
        }
    }
    func showAgentPrep(_ row:[String:Any]) {
        agentPrep = row
        guard loaded, !running else { return }
        guard process == nil, !gathering else { prepWaiting = true; return }   // one meeting helper at a time: this runs when the current one ends
        prepWaiting = false; gathering = true   // Cancel and Stop treat it like Fill in for me
        let text = row["preparedBrief"] as? String ?? row["summary"] as? String ?? ""
        let event = row["meetingEvent"] as? [String:Any] ?? [:]
        meetingTitle = event["title"] as? String ?? ""
        worker("--meeting-gather",["event":event,"prepared":text]) { [weak self] result in self?.gathering = false; self?.js("gathered",result) }
    }
    func gather(_ context: String) {
        guard loaded, !running, !gathering else { return }
        gathering = true; js("gathering", "Reading your current or next calendar event…")
        let g = generation
        calendarContext { [weak self] event, calendarNotice in
            DispatchQueue.main.async {
                guard let self, self.generation == g, self.gathering, self.panel != nil else { return }
                self.js("calendar", [.fullAccess, .notDetermined].contains(EKEventStore.authorizationStatus(for: .event)))   // a no turns the button into Allow Calendar
                self.js("gathering", "Searching related email and documents…")
                self.worker("--meeting-gather", ["event": event ?? [:], "text": String(context.prefix(20000))]) { [weak self] result in
                    guard let self, self.gathering else { return }
                    self.gathering = false
                    var reply = result
                    if reply["notice"] == nil, let calendarNotice { reply["notice"] = calendarNotice }
                    else if let calendarNotice, let notice = reply["notice"] as? String { reply["notice"] = calendarNotice + " " + notice }
                    self.js("gathered", reply)
                }
            }
        }
    }
    func cancelGather() { guard gathering else { return }; process?.terminate(); process = nil; gathering = false; js("gatherCancelled") }
    func next() {
        guard running, process == nil, answering == nil else { return }
        if let context = pendingBrief {
            pendingBrief = nil
            worker("--meeting-prep", ["text": context]) { [weak self] result in
                guard let self, running else { return }
                if !briefEdited && pendingBrief == nil {
                    if let b = result["brief"] as? String, !b.isEmpty { brief = String(b.prefix(meetingBriefLimit)); saveEvent(["kind": "notes", "text": brief]) }
                    js("prepared", result)
                }
                next()
            }
            return
        }
        guard !queue.isEmpty else { return }
        var data = queue.removeFirst(); let id = data["id"] as! Int
        data["brief"] = brief; data["style"] = style
        answering = id; measured[id] = data["at"] as? Double
        answerTimes[id] = ["final": data["finalAt"] as? Double ?? Date().timeIntervalSince1970,
                           "detected": data["detectedAt"] as? Double ?? Date().timeIntervalSince1970,
                           "model": Date().timeIntervalSince1970]
        js("thinking", id)
        sendAnswer(data)
    }
    func warmAnswer() {
        guard running, answerProcess == nil else { return }
        let p = py(["--meeting-live"]), input = Pipe(), output = Pipe()
        p.standardInput = input; p.standardOutput = output
        fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        answerProcess = p; answerInput = input; answerOutput = output
        let g = generation
        var buffer = Data()   // per process and only touched by its serial read callbacks, so a stale helper never feeds the next one
        output.fileHandleForReading.readabilityHandler = { [weak self, weak p] handle in
            guard let self, let p else { return }
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                DispatchQueue.main.async { [weak self, weak p] in
                    guard let self, let p, answerProcess === p else { return }
                    if answering != nil { finishAnswer(["error": "Could not finish"], process: p) }
                    else { answerProcess = nil; answerInput = nil; answerOutput = nil }
                }
                return
            }
            buffer.append(data)
            while let end = buffer.firstIndex(of: 10) {
                let line = buffer.prefix(upTo: end); buffer.removeSubrange(...end)
                guard let event = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any] else { continue }
                DispatchQueue.main.async { [weak self, weak p] in
                    guard let self, let p, generation == g, answerProcess === p, running, let id = answering else { return }
                    if event["event"] as? String == "text", let text = event["text"] as? String {
                        let first = event["at"] as? Double ?? Date().timeIntervalSince1970
                        if answerTimes[id]?["first"] == nil { var timing = answerTimes[id] ?? [:]; timing["first"] = first; answerTimes[id] = timing }
                        js("answerChunk", ["id": id, "text": text, "timing": answerTimes[id] ?? [:]])
                    }
                    if event["event"] as? String == "result" {
                        finishAnswer((event["result"] as? [String: Any]) ?? ["error": "Could not finish"], process: p)
                    }
                }
            }
        }
        do { try p.run() }
        catch { answerProcess = nil; answerInput = nil; answerOutput = nil }
    }
    func sendAnswer(_ data: [String: Any]) {
        if answerProcess == nil { warmAnswer() }
        answerQuestion = data["question"] as? String ?? ""
        guard let p = answerProcess, p.isRunning, let input = answerInput,
              var body = try? JSONSerialization.data(withJSONObject: data) else {
            if answering != nil { finishAnswer(["error": "Could not start"], process: answerProcess) }; return
        }
        body.append(10)
        do { try input.fileHandleForWriting.write(contentsOf: body); try input.fileHandleForWriting.close() }
        catch { finishAnswer(["error": "Could not start"], process: p) }
    }
    func finishAnswer(_ result: [String: Any], process p: Process?) {
        if let p, answerProcess !== p { return }
        guard let id = answering else { return }
        answerOutput?.fileHandleForReading.readabilityHandler = nil
        answerProcess = nil; answerInput = nil; answerOutput = nil; answering = nil
        var reply = result; reply["id"] = id
        if result["kind"] as? String == "answer" {
            saveEvent(["kind": "answer", "question": answerQuestion, "lines": result["lines"] ?? [], "at": Date().timeIntervalSince1970])
        }
        js("answer", reply)
        answerTimes[id] = nil
        warmAnswer(); next()
    }
    func worker(_ command: String, _ data: [String: Any], _ done: @escaping ([String: Any]) -> Void) {
        let p = py([command]), input = Pipe(), output = Pipe(); p.standardInput = input; p.standardOutput = output
        fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        process?.terminate(); process = p; let g = generation   // the one tracked helper; never orphan an older one
        do { try p.run() } catch { process = nil; done(["error": "Could not start"]); return }
        DispatchQueue.global().async { [weak self] in
            if let body = try? JSONSerialization.data(withJSONObject: data) { try? input.fileHandleForWriting.write(contentsOf: body) }
            try? input.fileHandleForWriting.close()
            let out = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
            let result = (try? JSONSerialization.jsonObject(with: out)) as? [String: Any] ?? ["error": "Could not finish"]
            DispatchQueue.main.async { [weak self] in
                guard let self, generation == g, process === p else { return }; process = nil; done(result)
                if prepWaiting, process == nil, let agentPrep { showAgentPrep(agentPrep) }
            }
        }
    }
    // The other people on the calendar event happening now: one is a 1:1's name, more are the names a group guess picks from.
    func callPeople() -> [String] {
        guard !room, EKEventStore.authorizationStatus(for: .event) == .fullAccess else { return [] }
        let now = Date()
        let event = calendar.events(matching: calendar.predicateForEvents(withStart: now.addingTimeInterval(-4 * 3600), end: now.addingTimeInterval(15 * 60), calendars: nil))
            .filter { !$0.isAllDay && $0.status != .canceled && $0.startDate <= now.addingTimeInterval(10 * 60) && $0.endDate > now }
            .max { $0.startDate < $1.startDate }
        return (event?.attendees ?? []).filter { !$0.isCurrentUser && $0.participantType == .person && $0.participantStatus != .declined }
            .compactMap { $0.name?.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty && !$0.contains("@") }
    }
    // Group calls: their lines share one channel, so every 8 lines (a minute apart at most once) Haiku names the ones the
    // conversation makes clear (a name said, a reply to a name). The rest stay "Them". Off with AI meeting summaries (the brain checks).
    func guessSpeakers() {
        guard running, !room, !demo, people.count != 1, guessing == nil, sinceGuess >= 8, Date().timeIntervalSince(lastGuess) >= 60 else { return }
        sinceGuess = 0; lastGuess = Date()
        let p = py(["--meeting-speakers"]), input = Pipe(), output = Pipe(); p.standardInput = input; p.standardOutput = output
        fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        do { try p.run() } catch { return }; guessing = p
        let g = generation, data: [String: Any] = ["people": people, "lines": Array(transcript.suffix(40))]
        DispatchQueue.global().async { [weak self] in
            if let body = try? JSONSerialization.data(withJSONObject: data) { try? input.fileHandleForWriting.write(contentsOf: body) }
            try? input.fileHandleForWriting.close()
            let out = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
            let names = ((try? JSONSerialization.jsonObject(with: out)) as? [String: Any])?["names"] as? [String: String] ?? [:]
            DispatchQueue.main.async { [weak self] in
                guard let self, guessing === p else { return }; guessing = nil
                let fresh = names.filter { self.named[$0.key] == nil }
                guard generation == g, running, !fresh.isEmpty else { return }
                named.merge(fresh) { $1 }; js("speakers", fresh); saveEvent(["kind": "speakers", "names": fresh])
            }
        }
    }
    func playDemo() {
        let p = py(["--meeting-demo"]), out = Pipe(); p.standardOutput = out; demoProcess = p
        let g = generation
        var buffer = Data()
        out.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { handle.readabilityHandler = nil; return }
            buffer += data
            while let end = buffer.firstIndex(of: 10) {
                let line = buffer.prefix(upTo: end); buffer.removeSubrange(...end)
                guard let result = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any] else { continue }
                DispatchQueue.main.async {
                    guard self?.generation == g && self?.running == true else { return }
                    if let end = result["ended"] as? Double { self?.demoEnds.append(end) }
                }
            }
        }
        try? p.run()
    }
    func cancelWork() {
        process?.terminate(); process = nil; finishing?.terminate(); finishing = nil; guessing?.terminate(); guessing = nil
        answerOutput?.fileHandleForReading.readabilityHandler = nil; answerProcess?.terminate()
        answerProcess = nil; answerInput = nil; answerOutput = nil; answerTimes = [:]; answerQuestion = ""
        queue = []; pendingBrief = nil; answering = nil; partialQuestion = nil; micPartialQuestion = nil; gathering = false; prepWaiting = false
        demoProcess?.terminate(); demoProcess = nil
    }
    func stop(paused: Bool = false) {
        if paused { finishing?.terminate(); finishing = nil }
        guard panel != nil else { return }
        if !running && (nudge != nil || transcript.isEmpty) { return discard() }   // pause or switch-off during a card: just close it
        guard running else { return }
        voice = false; voiceText = ""; voicePartial = ""
        pending += " " + partial; partial = ""; micPending += " " + micPartial; micPartial = ""
        flush(answer: false); flush(answer: false, mic: true); elapsed = Date().timeIntervalSince(began); running = false; minimized = false; generation += 1; starting?.cancel(); starting = nil; settle?.cancel(); micSettle?.cancel(); timer?.invalidate(); timer = nil
        cancelWork(); reading?.cancel(); reading = nil; micReading?.cancel(); micReading = nil
        analyzing?.cancel(); analyzing = nil; micAnalyzing?.cancel(); micAnalyzing = nil
        let capture = audio, an = analyzer, micAn = micAnalyzer; audio = nil; analyzer = nil; micAnalyzer = nil
        stopping = Task { await capture?.stop(); await an?.cancelAndFinishNow(); await micAn?.cancelAndFinishNow() }
        panel?.contentView?.layer?.cornerRadius = 18; bar.paint(); js("stopped", paused)
        js("saving", archive != nil)
        if !paused { finishArchive() } else { saveEvent(["kind": "checkpoint", "duration": elapsed]) }
        focus()
    }
    func discard() {
        if running { stop(paused:true) }; finishArchive(summarize:false); archive = nil; generation += 1; cancelWork(); transcript = []; brief = ""; pending = ""; partial = ""
        if let moveMonitor { NSEvent.removeMonitor(moveMonitor) }; moveMonitor = nil; dragOrigin = nil; mouseDown = nil
        if let screenObserver { NotificationCenter.default.removeObserver(screenObserver) }; screenObserver = nil
        nudge = nil; panel?.orderOut(nil); web?.configuration.userContentController.removeScriptMessageHandler(forName: "meeting"); web = nil; panel = nil
    }
    func material(_ paths: [String]) {
        let g = generation
        DispatchQueue.global().async { [weak self] in
            var text = "", accepted: [URL] = []
            for path in paths.prefix(8) {
                let url = URL(fileURLWithPath: path), ext = url.pathExtension.lowercased()
                guard ["pdf", "doc", "docx", "txt", "md"].contains(ext), ((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? Int.max) < 10_000_000 else { continue }
                let part = ext == "pdf" ? PDFDocument(url: url)?.string : ["doc", "docx"].contains(ext) ? (try? NSAttributedString(url: url, options: [:], documentAttributes: nil))?.string : (try? String(contentsOf: url, encoding: .utf8))
                guard let part, !part.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { continue }
                accepted.append(url); text += url.lastPathComponent + "\n" + String(part.prefix(20000)) + "\n"
            }
            DispatchQueue.main.async { [weak self] in
                guard let self, generation == g else { return }
                if accepted.isEmpty { js("error", "Add a readable PDF, Word, text or Markdown file under 10 MB"); return }
                js("material", String(text.prefix(20000)))
                for url in accepted {
                    let request = QLThumbnailGenerator.Request(fileAt: url, size: CGSize(width: 280, height: 180), scale: 2, representationTypes: .all)
                    QLThumbnailGenerator.shared.generateBestRepresentation(for: request) { [weak self] thumbnail, _ in
                        let png = thumbnail?.nsImage.tiffRepresentation.flatMap { NSBitmapImageRep(data: $0)?.representation(using: .png, properties: [:]) }
                        DispatchQueue.main.async {
                            guard self?.generation == g else { return }
                            self?.js("attachment", ["name": url.lastPathComponent, "folder": url.deletingLastPathComponent().path, "img": png.map { "data:image/png;base64," + $0.base64EncodedString() } ?? ""])
                        }
                    }
                }
            }
        }
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame else { return }   // the page itself, never a frame inside it
        guard message.webView === web else { return }
        guard let b = message.body as? [String: Any], let action = b["do"] as? String else { return }
        switch action {
        case "drag": if mouseDown != nil { dragOrigin = panel?.frame }
        case "resetFrame": resetFrame()
        case "rememberFrame": rememberFrame()
        case "ready": ready()
        case "start":
            if b["room"] as? Bool == true { callApp = "In person" } else if room { callApp = "Call" }
            if let style = b["style"] as? String { Prefs.set("meetingStyle", style); Prefs.set("meetingCustom", String((b["custom"] as? String ?? "").prefix(300))) }   // this call's pick is the next call's default
            start(b["context"] as? String ?? "")
        case "size": size(b["h"] as? Double ?? 0, reveal: b["reveal"] as? Int)
        case "resize": resize(b["w"] as? Double ?? 340, b["h"] as? Double ?? 650)
        case "compact": compact(b["on"] as? Bool ?? false)
        case "focus": nudge = nil; panel?.orderFrontRegardless(); focus()
        case "savePrep": if !running { Prefs.set("meetingPrep", String((b["text"] as? String ?? "").prefix(20000))) }
        case "gather": gather(b["context"] as? String ?? "")
        case "allowCalendar":   // macOS's own box the first time; System Settings once it won't ask again
            let context = b["context"] as? String ?? ""
            switch EKEventStore.authorizationStatus(for: .event) {
            case .fullAccess: js("calendar", true); gather(context)
            case .notDetermined:
                NSApp.activate(ignoringOtherApps: true)   // a menu-bar app's permission box can open behind other windows
                calendar.requestFullAccessToEvents { [weak self] ok, _ in DispatchQueue.main.async { self?.js("calendar", ok); if ok { self?.gather(context) } } }
            default: NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars")!)
            }
        case "cancelGather": cancelGather()
        case "prepare": if running { prepare(b["context"] as? String ?? "") }
        case "brief": if running { briefEdited = true; brief = String((b["text"] as? String ?? "").prefix(meetingBriefLimit)); saveEvent(["kind": "notes", "text": brief]) }
        case "stop": stop()
        case "voice":
            guard running else { return }
            if b["on"] as? Bool == true {
                guard micAnalyzer != nil, !demo else { js("voiceEnd"); js("error", "Voice asks need the microphone"); return }
                micPending += " " + micPartial; micPartial = ""; flush(answer: false, mic: true); voice = true; voiceText = ""; voicePartial = ""
            } else if voice { voice = false; voiceText = ""; voicePartial = ""; voiceTail = Date().addingTimeInterval(1.5) }
        case "pause": stop(paused: true)
        case "resume": start(brief)
        case "meetings": settings.open(tab: "meetings")
        case "delete": discard()
        case "save":
            guard !running else { return }; discard()
        case "deleteSaved":
            guard !running, let archive else { return }
            settings.meetings(["action": "delete", "id": archive.id]) { [weak self] result in
                if result["deleted"] != nil { self?.archive = nil; self?.discard() }
            }
        case "chooseFiles":
            let chooser = NSOpenPanel(); chooser.allowedContentTypes = ["pdf", "doc", "docx", "txt", "md"].compactMap { UTType(filenameExtension: $0) }; chooser.allowsMultipleSelection = true; chooser.canChooseDirectories = false
            chooser.begin { [weak self] response in if response == .OK { self?.material(chooser.urls.map(\.path)) } }
        case "ask", "answer":
            guard running else { return }
            let id = b["id"] as? Int ?? { serial += 1; return serial }()
            let question = b["text"] as? String ?? ""
            if action != "answer" { js("question", ["id": id, "text": question, "seconds": Int(Date().timeIntervalSince(began)), "auto": true]) }
            enqueue(id, question, best: true)
        case "screen":
            guard running else { return }; let g = generation
            Task { @MainActor [weak self] in
                guard let self else { return }
                do {
                    let all = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
                    let displayID = panel?.screen?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID
                    guard let d = all.displays.first(where: { $0.displayID == displayID }) ?? all.displays.first else { return }
                    let cfg = SCStreamConfiguration(); cfg.width = 1280; cfg.height = Int(1280 * Double(d.height) / Double(d.width))
                    let img = try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(display: d, excludingApplications: all.applications.filter { $0.bundleIdentifier == Bundle.main.bundleIdentifier }, exceptingWindows: []), configuration: cfg)
                    guard running, generation == g, let jpg = NSBitmapImageRep(cgImage: img).representation(using: .jpeg, properties: [.compressionFactor: 0.65]) else { return }
                    serial += 1; let question = b["text"] as? String ?? "Explain the shared slide."
                    js("question", ["id": serial, "text": question, "seconds": Int(Date().timeIntervalSince(began)), "auto": true]); enqueue(serial, question, best: true, image: jpg.base64EncodedString())
                } catch { js("error", "Could not look at screen") }
            }
        case "measured":
            guard let id = b["id"] as? Int, let shown = b["shownAt"] as? Double, let timing = b["timing"] as? [String: Double] else { return }
            let final = timing["final"] ?? timing["detected"] ?? shown, detected = timing["detected"] ?? final
            let model = timing["model"] ?? detected, first = timing["first"] ?? shown
            let event: [String: Any] = ["event": "meeting-answer-latency", "id": id,
                "finalToDetectedMs": round((detected - final) * 1000), "detectedToModelMs": round((model - detected) * 1000),
                "modelToFirstMs": round((first - model) * 1000), "firstToShownMs": round((shown - first) * 1000)]
            if let json = try? JSONSerialization.data(withJSONObject: event), let text = String(data: json, encoding: .utf8) { print(text); fflush(stdout) }
        case "copy": if let text = b["text"] as? String { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string) }
        case "share": shareText(b["text"] as? String ?? "", in: web, at: b["rect"] as? [Double] ?? [])
        case "remind": if let id = b["id"] as? String, let keys = b["keys"] as? [String] { dailyRecap.add("meeting:" + id, keys) { [weak self] in self?.js("reminded", $0) } }
        default: break
        }
    }
}
