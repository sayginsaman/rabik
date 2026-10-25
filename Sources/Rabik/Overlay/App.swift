// The box: listening, the worker it runs (rabik.py), and everything it shows. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

final class App: NSObject, WKScriptMessageHandler {
    let mini = MiniScreen()
    let quietAudio = AudioQuiet(layer: CoreAudioVolume(), changed: AudioRecovery.changed)
    let panel = KeyPanel(contentRect: NSRect(x: 0, y: 0, width: max(340, Prefs.num("boxW")), height: 76),
                        styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
    let web: WKWebView
    let engine = Mic()
    // Speech: Apple's SpeechAnalyzer (macOS 26+), on-device and free; punctuates and capitalizes.
    var feed: AsyncStream<AnalyzerInput>.Continuation?, analyzer: SpeechAnalyzer?, reading: Task<Void, Never>?
    var speechInputs: SpeechInputs?, speechInputID: UUID?, speechSegment = 0, activeSpeechSegment = 0
    var speechText: [Int: (base: String, done: String, live: String)] = [:]
    var nextFeed: AsyncStream<AnalyzerInput>.Continuation?, nextAnalyzer: SpeechAnalyzer?, nextReading: Task<Void, Never>?
    var nextSpeechInputID: UUID?, nextSpeechSegment = 0, nextSpeechRollover = 50.0
    var speechFormat: AVAudioFormat?, preparingSpeech = false   // what the model wants (found at launch and when the model changes)
    // Settings → Speech model: Apple's newer SpeechTranscriber, or the Dictation model the keyboard mic uses.
    // Dictation drops fastResults / frequentFinalization (Apple: faster but less accurate); asks keep them for live commands.
    func speechModule(dictate: Bool = false) -> any SpeechModule {
        let en = Locale(identifier: "en-US"), locale = en   // SpeechTranscriber rejects the Mac locale ("unsupported locale") even when SFSpeechRecognizer lists it: every voice ask died (1.5.0)
        if Prefs.str("speechModel") == "dictation" {
            return dictate ? DictationTranscriber(locale: en, contentHints: [.shortForm], transcriptionOptions: [.punctuation], reportingOptions: [.volatileResults], attributeOptions: [])
                : DictationTranscriber(locale: locale, preset: .progressiveShortDictation)
        }
        return dictate ? SpeechTranscriber(locale: en, transcriptionOptions: [], reportingOptions: [.volatileResults], attributeOptions: [])
            : SpeechTranscriber(locale: locale, preset: .progressiveTranscription)
    }
    func prepareSpeech() {   // make sure the speech model is installed, and learn its audio format
        guard !preparingSpeech else { return }
        preparingSpeech = true
        let m = speechModule()
        Task { [weak self] in
            if let r = try? await AssetInventory.assetInstallationRequest(supporting: [m]) { try? await r.downloadAndInstall() }
            let f = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [m])
            await MainActor.run { self?.speechFormat = f; self?.preparingSpeech = false }
        }
    }
    var text = "", answer = "", busy = false, speechFailed = false, gen = 0
    var agentCard = ""   // the hand-off or done card on screen: Esc picks its quiet choice
    var replyAgent = ""   // the agent whose done card was up when this ask began: talking clears the card, so it is kept here
    var showAgent = ""   // the task this ask showed (--agent-show): its work comes up when the ask ends
    var showRecap = ""   // the day this ask recapped ("summarize my day"): its card comes up when the ask ends
    var defaultKeys: [EventHotKeyRef] = []
    var defaultWanted = false, defaultObservers: [NSObjectProtocol] = []
    var proc: Process?, escRef: EventHotKeyRef?, warm: (p: Process, input: FileHandle, commit: String)?
    var commit = "", listenID = 0
    var consumed = 0, fastBusy = false, did: [String] = [], pause: DispatchWorkItem?   // "Act while I'm talking": commands done mid-sentence
    var fastProc: Process?, consumedText = "", liveRevised = false, targetScreen = ""
    var ahead = "", aheadItem: DispatchWorkItem?   // words the AI already started on while the user was still holding the keys
    var stops = 0   // each key release; tells a late "words landed" from a current one
    var dragging = false, fromTop = false, fromBottom = false   // moving or resizing the box; dragging the top edge keeps the bottom put, and the other way round
    var followTimer: Timer?
    var began = Date()   // when recording began, for the recording limit
    var composing = false, compH: CGFloat = 0, clickTalk = false, quiet: DispatchWorkItem?   // typing box focused / its height from the bottom; mic button = talk without keys
    var toggleTalk = false, shortcutDown = false, pausedNotice = Date.distantPast
    var dictating = false, dictateCleanup = false, dictateShortcutDown = false, dictateSelectionPending = false
    var dictatePressed = Date.distantPast, dictateTap: DispatchWorkItem?   // dictateTap: a quick tap waiting to see if a second one locks
    var dictateSelection: TextSelection?, dictationTargetApp: NSRunningApplication?, dictateProcess: Process?, dictateInput: FileHandle?, dictateOutput: FileHandle?, dictateID = 0, dictateBefore = ""
    var dictateSelectionRetried = false
    var askFile = ""   // safe mode: where the Allow / Don't Allow answer goes (rabik.py's gate waits on it)
    var askNeed: [String:Any] = [:]
    var agentMoveFile = "" { didSet { moveKey() } }   // set while rabik.py watches it: the running ask can move to an agent
    var moveRef: EventHotKeyRef?
    var retryOffer = false, offerText: String?   // answering a failure card preserves its original request
    var hovering = false, pinned = false, stuck = false, lastDone = Date.distantPast   // pinned: the user clicked the box, so only Esc / click-out / ✕ close it; stuck: the user dragged it, so only ✕
    var screenFrames = NSScreen.screens.map(\.frame)   // last display layout; a change in it makes an on-screen drawing stale
    var selection: TextSelection?, replacement: String?, mode = "replace", warmSel = ""   // mode: replace · delete · draft
    var selectionID = 0, selectionPending = false, replacing = false
    var mine = NSWorkspace.shared.frontmostApplication?.localizedName ?? ""   // the app the user's in, never Rabik itself
    var userApp = NSWorkspace.shared.frontmostApplication, guardUntil = Date.distantPast, allowUntil = Date.distantPast, userSwitch = Date.distantPast
    var allowUserApp = false
    var hiddenAtStart = Set<pid_t>()   // re-activating the user's app does not cover an app that unhid itself (an empty desktop shows it)
    func noteHidden() { hiddenAtStart = Set(NSWorkspace.shared.runningApplications.filter(\.isHidden).map(\.processIdentifier)) }
    let focusFile = (Prefs.path as NSString).deletingLastPathComponent + "/focus"   // rabik.py touches it when the user asked to see an app
    var focusFree: Bool { (try? FileManager.default.attributesOfItem(atPath: focusFile)[.modificationDate] as? Date).map { Date().timeIntervalSince($0) < 60 } ?? false }
    static func focusGuardActive(busy: Bool, recording: Bool, now: Date, until: Date, focusFree: Bool, workInFront: Bool = false) -> Bool {
        !workInFront && (busy || recording || now < until) && !focusFree
    }
    // An app raised for a hands click is not the user's app; recording it made the guard pull that app (an agent's Amazon tab) back forward.
    static func isUserApp(now: Date, allowUntil: Date, userSwitch: Date, allowUserApp: Bool = false) -> Bool {
        now > allowUntil || allowUserApp || now.timeIntervalSince(userSwitch) <= 0.6
    }
    let recent = (Prefs.path as NSString).deletingLastPathComponent + "/recent.jsonl"
    // ⌘-Tab, a Space swipe and Spotlight never reach a global event monitor, so the guard took them for an app jumping forward and pulled
    // the user back. Hardware ⌘/⌥ releases, clicks and gestures in the last second mean the user switched; plain typing does not.
    // Letting go of Rabik's own ⌃⌥ shortcut is a modifier change too, so one within 0.6 s of that release is not a switch.
    static var keysUp = Date.distantPast
    static func userJustSwitched() -> Bool {
        let ours = Date().timeIntervalSince(keysUp)
        return ([CGEventType.flagsChanged, .leftMouseDown, .rightMouseDown, .otherMouseDown] + [29, 20].compactMap { CGEventType(rawValue: $0) }).contains {
            let ago = CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: $0)
            return ago < 1 && !($0 == .flagsChanged && ago >= ours - 0.6 && ago <= ours + 0.1)
        }
    }
    func frame(_ requested: NSRect, animate: Bool = false) {   // keep the close button and composer reachable on every display
        let screen = NSScreen.screens.max { a, b in
            let x = a.visibleFrame.intersection(requested), y = b.visibleFrame.intersection(requested)
            return x.width * x.height < y.width * y.height
        } ?? NSScreen.main
        guard let screen else { return }
        let bounds = screen.visibleFrame.insetBy(dx: 8, dy: 8)
        var f = requested
        f.size.width = min(f.width, bounds.width); f.size.height = min(f.height, bounds.height)
        f.origin.x = min(max(f.minX, bounds.minX), bounds.maxX - f.width)
        f.origin.y = min(max(f.minY, bounds.minY), bounds.maxY - f.height)
        (animate ? panel.animator() : panel).setFrame(f, display: true); panel.invalidateShadow()
        js("limit", bounds.height)
    }
    // Which edges the point is on (window coordinates): 6 px edges, 14 px corners.
    func edges(_ p: NSPoint) -> (l: Bool, r: Bool, t: Bool, b: Bool)? {
        guard panel.frame.width >= 340 else { return nil }   // the dictation pill keeps its size; dragging it only moves it
        let w = panel.frame.width, h = panel.frame.height, c: CGFloat = 14
        let l = p.x < 6 || (p.x < c && (p.y < c || p.y > h - c)), r = p.x > w - 6 || (p.x > w - c && (p.y < c || p.y > h - c))
        let b = p.y < 6 || (p.y < c && (p.x < c || p.x > w - c)), t = p.y > h - 6 || (p.y > h - c && (p.x < c || p.x > w - c))
        return l || r || t || b ? (l, r, t, b) : nil
    }
    func overX(_ p: NSPoint) -> Bool { p.x > panel.frame.width - 42 && p.y > panel.frame.height - 42 }
    // Words the recognizer should expect: the user's app names plus a few of the user's own (free, on-device).
    var hints: [String] {
        let config = (Prefs.path as NSString).deletingLastPathComponent
        let shortcuts = (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: config + "/skills.json")))) as? [String: Any] ?? [:]
        var seen = Set<String>()
        return Array((DictationData.words + ["Rabik", profileName(config + "/me.json")] + shortcuts.keys.sorted() +
        [NSHomeDirectory() + "/Applications", "/Applications", "/System/Applications", "/System/Applications/Utilities"].flatMap {
            ((try? FileManager.default.contentsOfDirectory(atPath: $0)) ?? []).filter { $0.hasSuffix(".app") }.map { String($0.dropLast(4)) }
        }).filter { !$0.isEmpty && seen.insert($0).inserted }.prefix(DictationData.words.count + 100))
    }
    func sound(_ name: String, _ v: Float) { let s = NSSound(named: name); s?.volume = v; s?.play() }
    func cue(_ k: String) { let n = Prefs.str(k); if n != "None" { sound(n, Float(Prefs.num("volume"))) } }   // soundStart / soundRelease / soundDone / soundStop
    let drawing = ScreenDrawing()
    var drawingReply = false
    var pointContext: [String:Any]?
    var voice: Process?   // `say`: the Mac's system voice (a Siri voice if picked in Spoken Content); AVSpeechSynthesizer can't use Siri voices
    @discardableResult func shush() -> Bool {
        guard let v = voice else { return false }; voice = nil
        guard v.isRunning else { return false }; v.terminate(); return true
    }
    func deliver(_ a: String, aloud: Bool = true) {   // Settings: read answers aloud, copy them
        if Prefs.bool("autoCopy") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(a, forType: .string) }
        if Prefs.bool("speak") && aloud {
            siriVoice()   // a voice not downloaded at first use may become available later
            shush(); let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/say"); p.arguments = ["--", spoken(a)]
            p.terminationHandler = { [weak self] _ in DispatchQueue.main.async {
                guard let self, self.voice === p else { return }; self.voice = nil; self.hide(after: 2)
            } }
            try? p.run(); voice = p
        }
    }
    // A source chip under an answer (brain/sources.py): the meeting, day, page or file, person or fact the answer read.
    func openSource(_ s: [String: Any]) {
        let id = s["id"] as? String ?? ""
        switch s["kind"] as? String {
        case "meeting": Rabik.settings.open(tab: "meetings", then: "showMeeting", id)
        case "day": dailyRecap.open(id)
        case "person": Rabik.settings.open(tab: "people", then: "showPerson", id)
        case "fact": Rabik.settings.reveal(["c": s["c"] as? String ?? "", "t": s["t"] as? String ?? ""])
        case "activity":
            if let url = URL(string: id), ["http", "https"].contains(url.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(url) }
            else if id.hasPrefix("/"), FileManager.default.fileExists(atPath: id) {
                let file = URL(fileURLWithPath: id)   // a document opens; an app or a program only shows in Finder
                if file.pathExtension == "app" || FileManager.default.isExecutableFile(atPath: id) { NSWorkspace.shared.activateFileViewerSelecting([file]) }
                else { NSWorkspace.shared.open(file) }
            }
        default: break
        }
    }
    func linger(_ s: Double) -> Double { s * (["short": 0.5, "long": 2][Prefs.str("linger")] ?? 1) }
    func clearPointContext() {
        if let path = pointContext?["image"] as? String { try? FileManager.default.removeItem(atPath:path) }
        pointContext = nil; drawing.deselect(); js("point", false)
    }
    // While a drawing is up, the box glides to the nearest spot clear of its marks, and back home when it goes.
    var boxHome: NSPoint?   // where the box was before a drawing moved it; nil once the user drags it
    func avoidDrawing() {
        guard panel.isVisible, !dragging else { return }
        guard drawing.active else {
            DispatchQueue.main.async { [self] in   // a replaced drawing clears, then draws again at once
                guard !drawing.active else { return }
                if let home = boxHome { boxHome = nil; var f = panel.frame; f.origin = home; glide(f) }
                hide(after: 3)
            }
            return
        }
        let top = NSScreen.screens.first?.frame.maxY ?? 0
        let marks = drawing.occupied.map { CGRect(x:$0.minX,y:top-$0.maxY,width:$0.width,height:$0.height) }
        guard let spot = ScreenDrawing.clearSpot(panel.frame, avoiding:marks, in:NSScreen.screens.map(\.visibleFrame)), spot != panel.frame.origin else { return }
        if boxHome == nil { boxHome = panel.frame.origin }
        var f = panel.frame; f.origin = spot; glide(f)
    }
    func glide(_ f: NSRect, done: (() -> Void)? = nil) {
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion { frame(f); done?(); return }
        NSAnimationContext.runAnimationGroup({ $0.duration = 0.3; $0.timingFunction = CAMediaTimingFunction(name:.easeInEaseOut); panel.animator().setFrame(f, display:true) },
                                             completionHandler: { [weak self] in guard let self else { return }; if !dragging { frame(panel.frame) }; done?() })   // keeps it on a display and updates its height limit
    }
    func placeBox() {   // a new Box position: an open box glides there (unless the user placed it); a closed one shows it for a moment
        guard panel.isVisible else { show(); hide(after: 1.5); return }
        guard !stuck, !dragging else { return }
        var f = panel.frame; f.origin = boxOrigin(f.size, in: panel.screen?.visibleFrame ?? mouseScreen.visibleFrame); glide(f)
    }
    func followPointerScreen() {   // the box, typing box, answer and dictation pill alike
        guard panel.isVisible, !dragging, !hovering, var f = pointerFollow(panel.frame) else { return }
        if !stuck && boxSpot.hasSuffix("center") { f.origin.x = mouseScreen.visibleFrame.midX - f.width / 2 }   // a centred box stays centred on a wider or narrower display
        boxHome = nil; frame(f)
    }
    func startFollowingPointerScreen() {
        guard followTimer == nil else { return }
        followTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.followPointerScreen() }
    }
    func pointElement(_ point: CGPoint) -> String {
        guard AXIsProcessTrusted(), let app = userApp, !app.isTerminated else { return "" }
        var element: AXUIElement?
        guard AXUIElementCopyElementAtPosition(AXUIElementCreateApplication(app.processIdentifier),Float(point.x),Float(point.y),&element) == .success,
              let element else { return "" }
        let role = Hands.attribute(element,kAXRoleAttribute) as? String ?? "element"
        let label = Hands.mask(Hands.name(element))
        return String("\(app.localizedName ?? "App") \(role)\(label.isEmpty ? "" : ": " + label)".prefix(500))
    }
    // mark: one of Rabik's own marks the user clicked (points are its corners); the same context as a mark the user drew.
    func finishPoint(_ points: [CGPoint], mark: String = "") {
        guard let first = points.first else { drawing.clearInput(); return }
        let screen = NSScreen.screens.first {
            let id = $0.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()
            return CGDisplayBounds(id).contains(first)
        }
        guard let screen else { drawing.clearInput(); return }
        let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()
        let display = CGDisplayBounds(id), xs = points.map(\.x), ys = points.map(\.y)
        var region = CGRect(x:xs.min()!,y:ys.min()!,width:max(1,xs.max()!-xs.min()!),height:max(1,ys.max()!-ys.min()!)).insetBy(dx:-24,dy:-24)
        region = region.intersection(display)
        let path = NSTemporaryDirectory() + "rabik-point-" + UUID().uuidString + ".jpg"
        let capture = Process(); capture.executableURL = URL(fileURLWithPath:"/usr/sbin/screencapture")
        capture.arguments = ["-x","-R\(Int(region.minX)),\(Int(region.minY)),\(max(1,Int(region.width))),\(max(1,Int(region.height)))","-t","jpg",path]
        let capturing = (try? capture.run()) != nil
        if capturing { capture.waitUntilExit() }
        var context: [String:Any] = [
            "bounds":[Double(region.minX),Double(region.minY),Double(region.width),Double(region.height)],
            "path":points.map { [Double($0.x),Double($0.y)] },
            "element":pointElement(CGPoint(x:region.midX,y:region.midY))
        ]
        if !mark.isEmpty { context["mark"] = String(mark.prefix(1000)) }
        if capturing && capture.terminationStatus == 0 && FileManager.default.fileExists(atPath:path) { context["image"] = path }
        if context["image"] == nil && mark.isEmpty && (context["element"] as? String)?.isEmpty != false {
            drawing.clearInput(); js("notice","Couldn’t capture that mark."); return
        }
        if let old = pointContext?["image"] as? String { try? FileManager.default.removeItem(atPath:old) }   // a redrawn mark replaces the last crop
        pointContext = context
        if !mark.isEmpty { pinned = true; show() }
        js("point", ["active":drawing.inputMode,"marked":true,"picked":!mark.isEmpty,"thumb":(context["image"] as? String).map(pointThumb) ?? ""])
    }
    func pointThumb(_ path: String) -> String {   // the box's chip and the sent bubble's picture: a data URL, since the page can't read temporary files
        guard let image = NSImage(contentsOfFile:path), image.size.width > 0, image.size.height > 0 else { return "" }
        let scale = min(1, 480 / image.size.width, 300 / image.size.height)
        let small = NSImage(size:NSSize(width:image.size.width * scale,height:image.size.height * scale),flipped:false) { image.draw(in:$0); return true }
        guard let tiff = small.tiffRepresentation, let jpg = NSBitmapImageRep(data:tiff)?.representation(using:.jpeg,properties:[.compressionFactor:0.7]) else { return "" }
        return "data:image/jpeg;base64," + jpg.base64EncodedString()
    }
    func startPointing() {
        guard panel.isVisible else { return }
        guard !busy, !engine.isRunning else { js("notice","Finish or stop listening first."); return }
        drawing.beginInput { [weak self] points in self?.finishPoint(points) }
        pinned = true; js("point", ["active":true,"marked":false])
    }
    func finishPointing() {
        drawing.finishInput()
        if pointContext != nil { js("point", ["active":false,"marked":true]) }
    }

    override init() {
        let cfg = WKWebViewConfiguration()
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: max(340, Prefs.num("boxW")), height: 76), configuration: cfg)
        super.init()
        AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(), 0.5)   // main-thread AX polls (mini screen, drawings, dictation learning): a hung app costs 0.5 s, not 6 s
        drawing.resolve = { label, state in try Hands.drawAnchor(label,state:state) }
        drawing.cleanup = Hands.restoreAccessibility
        drawing.status = { [weak self] words in self?.js("msg",words) }
        drawing.speechEnabled = { Prefs.bool("speak") }
        drawing.autoSteps = { Prefs.str("guideSteps") != "next" }
        drawing.inputCleared = { [weak self] in self?.clearPointContext() }
        drawing.inputAway = { [weak self] in self?.finishPointing() }
        drawing.picked = { [weak self] r, words in self?.finishPoint([CGPoint(x:r.minX,y:r.minY),CGPoint(x:r.maxX,y:r.maxY)],mark:words) }
        drawing.changed = { [weak self] in self?.avoidDrawing() }
        cfg.userContentController.add(self, name: "h")
        cfg.userContentController.add(self, name: "c")
        web.setValue(false, forKey: "drawsBackground")
        web.autoresizingMask = [.width, .height]
        let bg = NSVisualEffectView(frame: web.frame)
        bg.material = .hudWindow; bg.state = .active; bg.wantsLayer = true; bg.autoresizingMask = [.width, .height]
        bg.appearance = NSAppearance(named: .darkAqua)   // stays dark over white pages, so the orb shows
        bg.layer?.cornerRadius = 18; bg.layer?.masksToBounds = true
        bg.maskImage = NSImage(size: NSSize(width: 37, height: 37), flipped: false) { NSColor.black.setFill(); NSBezierPath(roundedRect: $0, xRadius: 18, yRadius: 18).fill(); return true }
        bg.maskImage?.capInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18); bg.maskImage?.resizingMode = .stretch
        let tint = NSView(frame:web.frame); tint.wantsLayer = true; tint.autoresizingMask = [.width,.height]
        tint.layer?.backgroundColor = NSColor(calibratedRed:18/255,green:18/255,blue:20/255,alpha:0.85).cgColor   // light enough for the blur to show; measured over white it keeps small text AA (tests/contrast.html)
        bg.addSubview(tint); bg.addSubview(mini.clip)
        mini.publish = { [weak self] value in self?.js("mini",value) }
        mini.captureAllowed = { agentsUI.mini.target == nil }
        bg.addSubview(web)
        let tracker = Tracker(frame: web.frame)
        tracker.autoresizingMask = [.width, .height]
        tracker.onMove = { [weak self] p in
            guard let self else { return }
            if !hovering { js("hover", true) }
            hovering = true
            pointer("[\(p.x),\(web.frame.height - p.y)],\(overX(p) && edges(p) == nil)")   // the × is native's corner, wider than its dot
        }
        tracker.onExit = { [weak self] in
            guard let self else { return }
            hovering = false; js("hover", false); pointer("[]")
            if !busy { hide(after: 3) }   // mouse gone for a few seconds = close
        }
        bg.addSubview(tracker)
        panel.acceptsMouseMovedEvents = true
        panel.contentView = bg
        panel.level = .statusBar; panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        applySharing(panel)
        loadPage(web, "ui.html")
        // Click anywhere else closes the box once the answer is up; on the box: ✕ closes, elsewhere copies the answer.
        NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            guard let self, panel.isVisible, !busy, !engine.isRunning, !stuck, !drawing.active, !drawing.hasInput else { return }
            close(clear: false)
        }
        var grab: (mouse: NSPoint, origin: NSPoint)?, moved = false
        var sizing: (mouse: NSPoint, frame: NSRect, e: (l: Bool, r: Bool, t: Bool, b: Bool))?   // dragging an edge or corner
        NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .leftMouseDragged, .leftMouseUp]) { [weak self] e in
            guard let self else { return e }
            switch e.type {
            case .leftMouseDown:
                guard e.window == panel else { return e }
                let p = e.locationInWindow
                if let ed = edges(p), !(overX(p) && !ed.r && !ed.t) { sizing = (NSEvent.mouseLocation, panel.frame, ed); fromTop = ed.t; fromBottom = ed.b; pinned = true; dragging = true }
                else if overX(p) { close(clear: true) }
                else if p.y < compH { if !panel.isKeyWindow && replacement == nil { selection = TextSelection.capture() }; pinned = true; panel.makeKey(); panel.makeFirstResponder(web); return e }   // the typing box: a normal click; a waiting Insert/Replace keeps its target
                else { if !pillOn { pinned = true }; grab = (NSEvent.mouseLocation, panel.frame.origin); moved = false; dragging = true }   // the pill is not a box to keep
            case .leftMouseDragged:
                if let z = sizing {   // width from the side edges, height from the top/bottom; a corner does both
                    let m = NSEvent.mouseLocation, dx = m.x - z.mouse.x, dy = m.y - z.mouse.y
                    let w = min(900, max(340, z.frame.width + (z.e.r ? dx : z.e.l ? -dx : 0)))
                    var f = panel.frame; f.size.width = w; f.origin.x = z.e.l ? z.frame.maxX - w : z.frame.minX; frame(f)
                    Prefs.d["boxW"] = w
                    if z.e.t || z.e.b { js("hold", min(1000, max(120, z.frame.height + (z.e.b ? -dy : dy)))) }   // the page sets the height
                    return nil
                }
                guard let g = grab else { return e }
                let m = NSEvent.mouseLocation
                if abs(m.x - g.mouse.x) + abs(m.y - g.mouse.y) > 3 { moved = true; if !pillOn { stuck = true }; boxHome = nil }   // the user placed it: a drawing never moves it back
                var f = panel.frame; f.origin = NSPoint(x: g.origin.x + m.x - g.mouse.x, y: g.origin.y + m.y - g.mouse.y); frame(f)
            default:
                dragging = false
                if sizing != nil { sizing = nil; js("resizeDone"); DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in self?.fromTop = false; self?.fromBottom = false }; Prefs.set("boxH", Prefs.num("boxH")); return nil }   // saves both
                guard grab != nil else { return e }
                grab = nil
                if !moved {   // a click, not a drag: the page decides (answer = copy, anywhere else = type)
                    panel.makeKey(); panel.makeFirstResponder(web)
                    js("tap", [e.locationInWindow.x, panel.frame.height - e.locationInWindow.y])
                }
            }
            return nil
        }
        NotificationCenter.default.addObserver(forName: NSWindow.didResignKeyNotification, object: panel, queue: .main) { [weak self] _ in
            guard let self else { return }
            composing = false   // the page may not get a blur; the box must still be able to fade
            if !hovering && !busy { hide(after: 3) }
        }
        // Focus guard: while a task runs (and 2 s after it), an app that comes forward by itself (Spotify on play, open -a, a launch)
        // goes straight back behind the user's app. Not when the user asked to see it, switched apps themselves, or a menu press raises it.
        // Agents need no guard: their input is delivered in the background and their launches go behind (keep_behind).
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] n in
            guard let self, let a = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication, a != .current else { return }
            let now = Date()
            let workInFront = Prefs.str("workIn") == "front"
            if Self.focusGuardActive(busy:busy, recording:engine.isRunning, now:now, until:guardUntil, focusFree:focusFree, workInFront:workInFront),
               now > allowUntil, now.timeIntervalSince(userSwitch) > 0.6, !Self.userJustSwitched(),
               let u = userApp, !u.isTerminated, u != a { MiniScreen.activate(u.processIdentifier); if hiddenAtStart.contains(a.processIdentifier) { a.hide() }; return }
            if Self.isUserApp(now:now, allowUntil:allowUntil, userSwitch:userSwitch, allowUserApp:allowUserApp || workInFront) { mine = a.localizedName ?? ""; userApp = a }
        }
        NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown, .keyDown]) { [weak self] e in
            if e.type != .keyDown || e.modifierFlags.contains(.command) { self?.userSwitch = Date() }   // a click or ⌘-Tab: the user is choosing
        }
        DistributedNotificationCenter.default().addObserver(forName: .init("rabik.raise"), object: nil, queue: .main) { [weak self] n in
            self?.allowUntil = Date().addingTimeInterval(3)   // hands raise an app for a mouse click, then put the user's app back
            self?.allowUserApp = n.object as? String == "user"   // a voice focus request changes the user's app; a temporary hands raise does not
        }
        SFSpeechRecognizer.requestAuthorization { _ in }
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self else { return }
            let frames = NSScreen.screens.map(\.frame), moved = frames != screenFrames   // Dock/menu-bar changes also post this; only real display changes stale a drawing
            screenFrames = frames
            let hadDrawing = moved && (drawing.active || drawing.hasInput)
            let wasDictating = dictating, interrupted = hadDrawing && (engine.isRunning || dictating || busy)
            if interrupted { hush() }
            if hadDrawing { drawing.clear() }
            frame(panel.frame)
            if interrupted {
                let message = "The screen changed. Ask again to continue."
                if wasDictating { js("dictated", ["text": message, "ok": false]) } else { js("stopped", message) }
                hide(after: 3)
            } else if hadDrawing { js("notice", "The screen changed. Ask again to continue.") }
        }
        prepareSpeech()
        AVCaptureDevice.requestAccess(for: .audio) { _ in }
    }

    // The page reports its height; grow the box down from the top-left corner. "c": the typing box.
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard m.frameInfo.isMainFrame else { return }   // the page itself, never a frame inside it
        if m.name == "c", let b = m.body as? [String: Any] {
            if b["learnedUndo"] != nil, let word = learnedWord {
                if DictationData.forget(word) {
                    learnedWord = nil; js("dictated", ["text": "Forgot that spelling", "ok": true]); hide(after: 2)
                    Rabik.settings.send("dictation", DictationData.state())
                }
            }
            if b["dictationHistory"] != nil { hide(after: 0); Rabik.settings.open(tab: "dictation") }
            if let enabled = b["agentDefault"] as? Bool { defaultKey(enabled) }
            if let value = b["miniRect"] as? [String:Any] { mini.layout(value) }
            // a click on the mini screen = the user wants to see it: the focus guard stands aside
            if b["miniOpen"] != nil { allowUntil = Date().addingTimeInterval(3); allowUserApp = true; userSwitch = Date(); mini.open(); if !busy { mini.reset(); hide(after:3) } }
            if b["miniClear"] != nil { mini.reset() }
            if let h = b["comp"] as? NSNumber { compH = CGFloat(h.doubleValue) }
            if let h = b["boxH"] as? NSNumber { Prefs.d["boxH"] = h.doubleValue }   // saved when the drag ends
            if let f = b["focus"] as? Bool {
                composing = f
                if !f && !hovering && !busy { hide(after: 3) }
            }
            if b["type"] != nil {   // typing wins; a pending failure card keeps its worker
                if engine.isRunning { if retryOffer { stopOfferInput() } else { hush() } }
                else if busy && proc == nil && offerText == nil && !dictating && text.isEmpty { hush(); js("msg", "") }   // released, nothing heard, still finalizing
            }
            if let s = b["link"] as? String, let url = URL(string: s), ["https", "http", "mailto"].contains(url.scheme?.lowercased() ?? "") {   // a link in an answer: the user's browser
                allowUntil = Date().addingTimeInterval(3); allowUserApp = true; NSWorkspace.shared.open(url)
            }
            if let a = b["copy"] as? String, !a.isEmpty {
                NSPasteboard.general.clearContents(); NSPasteboard.general.setString(a, forType: .string); js("copied")
            }
            if ["agentOpen","agentLater","agentConnect"].contains(where:{ b[$0] != nil }) { agentCard = ""; defaultKey(false) }
            if b["agentGone"] != nil { agentCard = ""; escape() }   // the card left another way: Esc does its usual job
            if let add = b["recapAdd"] as? [String: Any], let source = add["source"] as? String, let keys = add["keys"] as? [String] {
                dailyRecap.add(source, keys) { [weak self] in self?.js("recapAdded", $0) }
            }
            if b["recapLater"] != nil { pinned = false; hide(after: 1) }
            if let id = b["agentOpen"] as? String {
                if let target = b["target"] as? String { agentsUI.open(id,target:target) }
                else { agentsUI.openView(id) }   // the done card's Return action opens the report; its artifact buttons open artifacts
                agentsUI.dismissPing(id)
            }
            if let id = b["agentLater"] as? String { agentsUI.dismissPing(id) }
            if let id = b["agentConnect"] as? String { NSWorkspace.shared.open(URL(string:"https://claude.ai/settings/connectors")!); agentsUI.dismissPing(id) }
            if b["agents"] != nil { agentsUI.openView() }
            if b["setup"] != nil { onboarding.open() }
            if b["workerRetry"] != nil, !busy { pinned = false; typed(text, keep: true) }
            if b["resume"] != nil {
                Rabik.settings.apply("paused", false); Rabik.settings.push()
                if !Prefs.bool("paused") { js("paused", false); hide(after: 1.5) }
            }
            if b["replace"] != nil, !busy { applyReplacement() }
            if b["retry"] != nil, !busy, !engine.isRunning { typed(text, keep: true) }
            if let t = b["send"] as? String { typed(t, keep: true) }
            if b["point"] != nil { drawing.inputMode ? finishPointing() : startPointing() }
            if b["pointClear"] != nil { if drawing.hasInput { drawing.clearInput() } else { clearPointContext() } }   // a drawn mark, or a selected one of Rabik's
            if b["pointCoached"] != nil { Prefs.set("pointCoached", true) }
            if b["mic"] != nil && (!busy || retryOffer) && !engine.isRunning { clickTalk = true; start(); if !engine.isRunning { clickTalk = false } }
            if b["ready"] != nil { js("size", Prefs.num("boxH")); if Prefs.bool("tips") && !Prefs.bool("pointCoached") { js("pointCoach") } }
            if b["safe"] != nil { Prefs.set("safe", true); js("mode", true); Rabik.settings.push() }
            if let m = b["model"] as? String {   // picked in the box: the same setting Settings shows; a worker warmed on the old model goes
                Rabik.settings.apply(Prefs.str("apiBase").isEmpty ? "routing" : "apiModel", m); Rabik.settings.push()
            }
            if b["models"] != nil, !Prefs.str("apiBase").isEmpty {   // a custom server's list can change: ask it again
                let base = Prefs.str("apiBase"), key = Prefs.str("apiKey")
                DispatchQueue.global().async { [weak self] in
                    let p = py(["--models"], ["RABIK_PROBE_BASE":base, "RABIK_PROBE_KEY":key]), out = Pipe(); p.standardOutput = out
                    let d = runToEnd(p, out)
                    let list = (try? JSONSerialization.jsonObject(with: d)) as? [String] ?? []
                    DispatchQueue.main.async { if base == Prefs.str("apiBase"), key == Prefs.str("apiKey"), !list.isEmpty { self?.serverModels = list; self?.js("models", self?.modelChoices() ?? [:]) } }
                }
            }
            if let i = b["pick"] as? String, !askFile.isEmpty {
                if retryOffer {
                    stopOfferInput(); retryOffer = false
                }
                try? i.write(toFile: askFile, atomically: true, encoding: .utf8); askFile = ""
            }   // an index, or "" = none; failure cards also use r/n
            if b["off"] as? String == "tips" { Rabik.settings.apply("tips", false); Rabik.settings.push() }   // a tip's own "Turn off"; never safe mode
            if let v = b["improve"] as? Bool { Rabik.settings.apply("improve", v); Rabik.settings.push() }
            if let item = b["memory"] as? [String: Any] { Rabik.settings.reveal(item) }   // a receipt's item: Settings → Memory, at that item
            if let source = b["source"] as? [String: Any] { openSource(source) }
            if let ok = b["allow"] as? Bool, !askFile.isEmpty { allow(ok) }
            return
        }
        let size = ((m.body as? [NSNumber]) ?? [m.body as? NSNumber].compactMap { $0 }).map { CGFloat($0.doubleValue) }
        guard let h = size.last, h > 0 else { return }
        var f = panel.frame
        if fromBottom || !fromTop && !boxAtBottom { f.origin.y = f.maxY - h }   // grows away from its edge (Box position); a dragged edge moves, the other stays
        f.size.height = h
        let pillWidth = size.count == 2 && pillOn ? size[0] : nil   // a late one from before pill(false) must not shrink the box
        if let w = pillWidth, w > 0 { f = boxWidth(f, w) }
        guard f != panel.frame else { return }
        if pillWidth != nil && panel.isVisible && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {   // the pill morphs between its states
            NSAnimationContext.runAnimationGroup({ $0.duration = 0.22; $0.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut); frame(f, animate: true) },
                                                 completionHandler: { [self] in panel.invalidateShadow() })
        } else { frame(f) }
        if drawing.active && !stuck && !dragging { avoidDrawing() }   // grew onto a mark; a box the user placed waits for the next step
    }

    func js(_ call: String, _ arg: Any? = nil) { callJS(web, "ui." + call, arg.map { [$0] } ?? []) }
    var pointerNext: String?, pointerBusy = false, pointerHand = false
    func pointer(_ args: String) {   // Rabik never activates, so WebKit runs no :hover or cursor in the box: the page marks .hot and says if the cursor is a hand
        pointerNext = args
        guard !pointerBusy else { return }   // one evaluation in flight; later moves coalesce into the newest
        pointerNext = nil; pointerBusy = true
        web.evaluateJavaScript("ui.pointer(\(args))") { [weak self] hand, _ in
            guard let self else { return }
            pointerBusy = false
            if (hand as? Bool ?? false) != pointerHand { pointerHand.toggle(); (pointerHand ? NSCursor.pointingHand : NSCursor.arrow).set() }
            if let next = pointerNext { pointer(next) }
        }
    }

    var serverModels: [String] = []
    func modelChoices() -> [String: Any] {
        if Prefs.str("client") != "claude" { return ["list": [], "pick": ""] }
        if Prefs.str("apiBase").isEmpty { return ["list": ["cheapest", "balanced", "capable"], "pick": Prefs.str("routing")] }
        let pick = Prefs.str("apiModel").isEmpty ? serverModels.first ?? "" : Prefs.str("apiModel")
        return ["list": serverModels.isEmpty ? [pick].filter { !$0.isEmpty } : serverModels, "pick": pick]
    }
    // Settings → General → Box position: where on the pointer's display the box opens. It grows away from that edge,
    // and a new width (the dictation pill, the saved size) keeps its side, or its middle, where it was.
    var boxSpot: String {
        let spot = Prefs.str("boxPosition")
        return ["top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"].contains(spot) ? spot : "top-center"
    }
    var boxAtBottom: Bool { boxSpot.hasPrefix("bottom") }
    func boxOrigin(_ size: NSSize, in vf: NSRect) -> NSPoint {
        let x = boxSpot.hasSuffix("left") ? vf.minX + 14 : boxSpot.hasSuffix("right") ? vf.maxX - size.width - 14 : vf.midX - size.width / 2
        return NSPoint(x: x, y: boxAtBottom ? vf.minY + 10 : vf.maxY - size.height - 10)
    }
    func boxWidth(_ f: NSRect, _ w: CGFloat) -> NSRect {
        var g = f; g.size.width = w
        g.origin.x = boxSpot.hasSuffix("left") ? f.minX : boxSpot.hasSuffix("right") ? f.maxX - w : f.midX - w / 2
        return g
    }
    func show() {
        gen += 1; js("visible", true); js("mode", Prefs.bool("safe")); js("models", modelChoices())
        startFollowingPointerScreen()
        if panel.isVisible {   // still up: stay where the user dragged it
            NSAnimationContext.runAnimationGroup { $0.duration = 0.18; panel.animator().alphaValue = 1 }
            return
        }
        defer { if drawing.active { avoidDrawing() } }
        panel.setFrameOrigin(boxOrigin(panel.frame.size, in: mouseScreen.visibleFrame))   // open where the user is looking: the cursor's screen
        frame(panel.frame)
        panel.alphaValue = 0
        panel.orderFrontRegardless()
        if escRef == nil {
            RegisterEventHotKey(UInt32(kVK_Escape), 0, EventHotKeyID(signature: 0x41545443, id: 2), GetApplicationEventTarget(), 0, &escRef)
        }
        NSAnimationContext.runAnimationGroup { $0.duration = 0.18; panel.animator().alphaValue = 1 }
    }

    func hide(after s: Double) {
        let g = gen
        DispatchQueue.main.asyncAfter(deadline: .now() + s) { [self] in
            guard g == gen, !busy, !engine.isRunning, !hovering else { return }
            guard !pinned, !stuck, !composing, !mini.holds, !drawing.active, !drawing.hasInput, ringGone == nil, voice?.isRunning != true else {   // moved or drawn on: only ✕ (Esc for a drawing); an answer's ring keeps its text up
                if pillOn && !dictating { pill(false) }   // the box stays up for its answer or drawing: give it back, not a pill stuck on its check
                return
            }
            NSAnimationContext.runAnimationGroup({ $0.duration = 0.3; panel.animator().alphaValue = 0 },
                                                 completionHandler: { [self] in if g == gen { gone() } })
        }
    }


    func defaultKey(_ enabled: Bool) {
        defaultWanted = enabled
        if defaultObservers.isEmpty {
            for name in [NSWindow.didBecomeKeyNotification,NSWindow.didResignKeyNotification] {
                defaultObservers.append(NotificationCenter.default.addObserver(forName:name,object:nil,queue:.main) { [weak self] _ in DispatchQueue.main.async { self?.refreshDefaultKeys() } })
            }
        }
        refreshDefaultKeys()
    }
    func refreshDefaultKeys() {
        defaultKeys.forEach { UnregisterEventHotKey($0) }; defaultKeys = []
        guard defaultWanted, panel.isVisible, NSApp.keyWindow == nil || NSApp.keyWindow === panel else { return }
        for (code,id) in [(kVK_Return,3),(kVK_ANSI_KeypadEnter,4)] {
            var ref: EventHotKeyRef?
            if RegisterEventHotKey(UInt32(code),0,EventHotKeyID(signature:0x41545443,id:UInt32(id)),GetApplicationEventTarget(),0,&ref) == noErr, let ref { defaultKeys.append(ref) }
        }
    }
    func defaultAction() {
        guard panel.isVisible, !defaultKeys.isEmpty else { return }
        defaultKey(false); js("agentDefaultAction")
    }
    // ⌃⌥↩ moves the running ask to an agent from any app; held only while there is one to move
    func moveKey() {
        if let r = moveRef { UnregisterEventHotKey(r); moveRef = nil }
        guard !agentMoveFile.isEmpty else { return }
        RegisterEventHotKey(UInt32(kVK_Return), UInt32(controlKey | optionKey), EventHotKeyID(signature: 0x41545443, id: 5), GetApplicationEventTarget(), 0, &moveRef)
    }
    func moveToAgent() {   // a card waiting for the user goes with the ask: the agent asks again itself
        guard busy, !agentMoveFile.isEmpty else { return }
        do { try "go".write(toFile:agentMoveFile,atomically:true,encoding:.utf8); agentMoveFile = ""; askFile = ""; retryOffer = false; js("movePending") }
        catch { js("moveFailed") }
    }
    func gone() {
        defaultKey(false)
        mini.reset()
        followTimer?.invalidate(); followTimer = nil
        panel.orderOut(nil); agentCard = ""; pinned = false; stuck = false; boxHome = nil; composing = false; js("compose", false); js("visible", false)
        if hovering { hovering = false; js("hover", false); pointer("[]") }   // a hidden panel gets no mouseExited
        pill(false)
        if let r = escRef { UnregisterEventHotKey(r); escRef = nil }
    }
    var pillOn = false
    func pill(_ on: Bool) {   // dictation is a pill the page sizes (a hidden one starts as the dot it grows from); the box gets its saved width back
        pillOn = on; js("dictate", on)
        guard !on || !panel.isVisible else { return }
        let w = CGFloat(on ? 36 : max(340, Prefs.num("boxW")))
        var f = panel.frame; guard f.width != w || on && f.height != w else { return }
        f = boxWidth(f, w)
        if on { if !boxAtBottom { f.origin.y = f.maxY - w }; f.size.height = w }
        frame(f)
    }

    func allow(_ ok: Bool) {
        let path = askFile, need = askNeed["need"] as? String ?? "", app = askNeed["app"] as? String ?? ""
        if ok && need == "page-js" { Prefs.set("pageJS", true) }
        guard ok, !need.isEmpty, need != "page-js" else {
            try? (ok ? "y" : "n").write(toFile:path, atomically:true, encoding:.utf8); askFile = ""; return
        }
        onboarding.allow(need, app:app)
        var tries = 0
        Timer.scheduledTimer(withTimeInterval:1, repeats:true) { [weak self] t in
            tries += 1
            guard let self, self.askFile == path, tries < 900 else { t.invalidate(); return }
            DispatchQueue.global().async {
                if Onboarding.granted(need, app:app) { DispatchQueue.main.async {
                    guard self.askFile == path else { return }
                    try? "y".write(toFile:path, atomically:true, encoding:.utf8); self.askFile = ""; t.invalidate()
                } }
            }
        }
    }

    // Esc: stop listening, stop the answer, or close the box.
    // One layer per press: the user's mark, voice, listening, a card, the answer, then the drawing, then the box.
    func escape() {
        if drawing.hasInput { drawing.clearInput(); return }
        if shush() { return }
        if dictating { return cancel() }
        if engine.isRunning {
            hush(); cue("soundStop"); js("stopped", "Stopped listening"); hide(after: 1.5)
        } else if !agentCard.isEmpty, panel.isVisible {
            js("agentEscape")
        } else if busy {
            cancel()
        } else if drawing.active {
            drawing.clear()
        } else if panel.isVisible {
            close(clear: false)
        }
    }

    func hush() { hush(keepReply: false) }
    func hush(keepReply: Bool, keepWarm: Bool = false) {   // stop listening, drop what was heard, say nothing; a drawing stays until Esc, its ✕ or close
        if !keepReply { drawingReply = false }
        mini.reset()
        engine.stop(); speechInputs?.finishAll(); reading?.cancel(); nextReading?.cancel(); pause?.cancel()
        if !keepWarm { unwarm() }
        quietAudio.end()
        clickTalk = false; toggleTalk = false; quiet?.cancel(); stops += 1   // stops: a late "words landed" from this listen does nothing
        listenID += 1; selectionID += 1; selectionPending = false; replacing = false
        dictating = false; dictateID += 1; dictateSelectionPending = false; dictateSelection = nil
        stopDictationCleanup()
        cancelFast()
        aheadItem?.cancel(); dropAhead()
        proc?.terminate(); proc = nil; askFile = ""; agentMoveFile = ""; replacement = nil; retryOffer = false
        if let old = offerText { text = old }; offerText = nil
        let an = analyzer, next = nextAnalyzer
        nextFeed = nil; nextAnalyzer = nil; nextReading = nil; nextSpeechInputID = nil; nextSpeechSegment = 0
        Task { await an?.cancelAndFinishNow(); await next?.cancelAndFinishNow() }
        busy = false   // an early start dropped above never reports back (its exit handler sees proc changed)
    }

    func stopOfferInput() {
        engine.stop()
        unwarm()
        quietAudio.end()
        speechInputs?.finishAll(); reading?.cancel(); nextReading?.cancel(); quiet?.cancel(); clickTalk = false; toggleTalk = false; listenID += 1; stops += 1
        if let old = offerText { text = old }; offerText = nil
        let an = analyzer, next = nextAnalyzer
        nextFeed = nil; nextAnalyzer = nil; nextReading = nil; nextSpeechInputID = nil; nextSpeechSegment = 0
        Task { await an?.cancelAndFinishNow(); await next?.cancelAndFinishNow() }
    }

    func dismiss() {   // the shortcut again before anything happened: say so, then go
        if engine.isRunning { hush() }
        cue("soundStop"); js("stopped", "Answer stopped")
        let g = gen; DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [self] in if g == gen { close(clear: false) } }
    }

    func cancel() {
        if dictating { cue("soundStop"); return close(clear: false) }   // listening or finishing: fade out, nothing inserted
        hush(); shush()
        cue("soundStop"); js("stopped", "Answer stopped"); hide(after: 1.5)
    }

    // ✕ also ends the conversation; clicking away or timing out keeps it for 5 minutes.
    func close(clear: Bool) {
        let pending = clear || replacement == nil ? nil : (replacement, selection)
        shush(); hush(); drawing.clear(); unpoint()   // gone means quiet: no mic, no voice, no answer, no drawing or ring
        if let pending { replacement = pending.0; selection = pending.1 }   // a hidden Insert/Replace keeps its validated target
        if clear { try? FileManager.default.removeItem(atPath: recent); lastDone = .distantPast }
        gen += 1
        let g = gen
        NSAnimationContext.runAnimationGroup({ $0.duration = 0.2; panel.animator().alphaValue = 0 },
                                             completionHandler: { [self] in if g == gen { gone() } })
    }

    func shortcut(_ pressed: Bool) {
        if meeting.running { if pressed { meeting.focus() }; return }
        if !pressed {
            shortcutDown = false; Self.keysUp = Date()
            guard engine.isRunning && !toggleTalk && !clickTalk else { return }
            // a tap: nobody spoke in 0.3 s, so stop now instead of waiting on the recognizer to report nothing
            if text.isEmpty && offerText == nil && Date().timeIntervalSince(began) < 0.3 { hush(); js("msg", ""); return hide(after: 0.2) }
            stop()
            return
        }
        guard !shortcutDown else { return }   // one action per physical press, including key repeat
        shortcutDown = true
        guard !Prefs.bool("paused") else {
            if Date().timeIntervalSince(pausedNotice) > 4 { pausedNotice = Date(); js("paused"); show(); hide(after: 4) }
            return
        }
        if shush() { return }
        if engine.isRunning { return toggleTalk ? stop() : dismiss() }
        if busy && !retryOffer && !drawing.active { return cancel() }
        start()
    }

    func prepareForInactiveSession() {
        shortcutDown = false; dictateShortcutDown = false
        dictateTap?.cancel(); dictateTap = nil
        let transient = engine.isRunning || dictating || drawing.active || drawing.hasInput
        if engine.isRunning || dictating { hush() }
        if drawing.active || drawing.hasInput { drawing.clear() }
        quietAudio.end(immediate: true)
        if transient { gone() }
    }

    // Hold to talk, release to insert. A quick tap waits a moment: a second tap locks it on until the next press (toggleTalk).
    func dictateShortcut(_ pressed: Bool) {
        if !pressed {
            dictateShortcutDown = false; Self.keysUp = Date()
            guard engine.isRunning, dictating, !toggleTalk, dictateTap == nil else { return }
            if Date().timeIntervalSince(dictatePressed) > 0.3 { return stop() }
            let id = listenID, tap = DispatchWorkItem { [weak self] in
                guard let self else { return }
                dictateTap = nil; if listenID == id { stop() }
            }
            dictateTap = tap; DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: tap)
            return
        }
        guard !dictateShortcutDown else { return }
        dictateShortcutDown = true
        guard !Prefs.bool("paused"), !meeting.running else { return }
        if let tap = dictateTap {
            tap.cancel(); dictateTap = nil
            if engine.isRunning && dictating { toggleTalk = true; js("locked", true); return }
        }
        if engine.isRunning { if dictating { if toggleTalk { stop() } else { dismiss() } }; return }
        if busy { if dictating { cancel() }; return }
        dictatePressed = Date()
        startDictation()
    }
    // A modifier-only dictation shortcut held for another key (fn+Delete, fn+←): that key's own shortcut, so a press
    // that has heard nothing yet goes away quietly. Once words are heard it stays dictation.
    func dictateChord() -> Bool {
        guard dictateShortcutDown, dictating, !toggleTalk, text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        dictateShortcutDown = false; dictateTap?.cancel(); dictateTap = nil
        close(clear: false); return true
    }

    func review(_ message: String) {
        hush(); js("msg", message)
        pinned = true; panel.makeKey(); panel.makeFirstResponder(web); js("draft", text)
    }

    func recordingLimit() {
        if let old = offerText { let partial = text; stopOfferInput(); text = old; js("draft", partial); return }
        if toggleTalk { review("Recording paused after 60 seconds. Review your words and press Return to send.") }
        else { stop() }
    }

    func captureSelection() {
        selectionID += 1; let id = selectionID
        selection = nil; selectionPending = Prefs.bool("selection")
        guard selectionPending else { return }
        let front = NSWorkspace.shared.frontmostApplication
        DispatchQueue.global().async { [weak self] in
            let selected = TextSelection.capture(front, enabled: true)
            DispatchQueue.main.async { [weak self] in
                guard let self, self.selectionID == id else { return }
                self.selectionPending = false; self.selection = Prefs.bool("selection") ? selected : nil
                if let selection = self.selection { self.js("selected", selection.text) }
                if self.warm != nil && self.warmSel != self.selKey { self.unwarm(); self.warm = self.spawn() }
            }
        }
    }

    var selKey: String { Prefs.bool("selection") ? selection.map { $0.caret ? "\u{1}" : $0.text } ?? "" : "" }   // \u{1}: no highlight, the cursor sits in a text box

    func captureDictationSelection(retry: Bool = false) {
        if !retry {
            dictateSeconds = 0
            dictationTargetApp = NSWorkspace.shared.frontmostApplication
            dictationAppName = dictationTargetApp?.localizedName ?? "App"
            dictateID += 1; dictateSelection = nil; dictateBefore = ""; dictateSelectionRetried = false
        }
        let id = dictateID, front = dictationTargetApp, cleanup = dictateCleanup
        dictateSelectionPending = true
        DispatchQueue.global().async { [weak self] in
            var secureField = false
            let selected = TextSelection.capture(front, enabled: true, allowEmpty: true, keyboardFallback: !retry, onSecure: { secureField = true })   // the retry only counts a real text box
            // Clean up reads the text before the cursor for names and terms.
            let before = selected.flatMap { s -> String? in
                guard cleanup, let value = s.value as NSString?, let r = s.range, r.location >= 0, r.location <= value.length else { return nil }
                return String(value.substring(to: r.location).suffix(600))
            } ?? ""
            DispatchQueue.main.async { [weak self] in
                guard let self, dictating, dictateID == id, !retry || dictateSelectionPending else { return }   // a retry that ran out of time already moved on
                if secureField {
                    hush(); js("dictated", ["text": "Dictation is off in secure fields", "ok": false]); hide(after: 3); return
                }
                dictateSelectionPending = false
                guard let selected else {   // no text field: the words still go to History ("Nothing selected to insert")
                    if AXIsProcessTrusted() {
                        if retry { finishDictation() }
                        return
                    }
                    hush(); js("dictated", ["text": "Allow Accessibility in System Settings → Privacy & Security → Accessibility", "ok": false]); hide(after: 6); return
                }
                dictateSelection = selected
                dictateBefore = before
                if retry { finishDictation() }
            }
        }
    }

    func start() { start(dictate: false) }
    func startDictation() { start(dictate: true) }
    func beginSpeechSegment(_ base: String, listeningID: Int) -> (feed: AsyncStream<AnalyzerInput>.Continuation, inputID: UUID, analyzer: SpeechAnalyzer, reading: Task<Void, Never>, segment: Int) {
        let tr = speechModule(dictate: dictating)
        let (stream, cont) = AsyncStream<AnalyzerInput>.makeStream()
        let an = SpeechAnalyzer(modules: [tr])
        speechSegment += 1; let segment = speechSegment
        speechText[segment] = (base, "", "")
        let inputID = speechInputs!.add(cont)
        let ctx = AnalysisContext(); ctx.contextualStrings[.general] = hints
        Task { try? await an.setContext(ctx); try? await an.start(inputSequence: stream) }
        let rd = Task { [weak self] in
            do {
                if let d = tr as? DictationTranscriber {
                    for try await r in d.results {
                        await MainActor.run { self?.speechPiece(String(r.text.characters), final: r.isFinal, segment: segment, listeningID: listeningID) }
                    }
                } else if let t = tr as? SpeechTranscriber {
                    for try await r in t.results {
                        await MainActor.run { self?.speechPiece(String(r.text.characters), final: r.isFinal, segment: segment, listeningID: listeningID) }
                    }
                }
            } catch {
                await MainActor.run {
                    if self?.listenID == listeningID && (self?.activeSpeechSegment == segment || self?.nextSpeechSegment == segment) { self?.speechFailed = true }
                }
            }
        }
        return (cont, inputID, an, rd, segment)
    }

    func speechPiece(_ piece: String, final: Bool, segment: Int, listeningID: Int) {
        guard self.listenID == listeningID, var part = speechText[segment] else { return }
        if final { part.done += piece; part.live = "" } else { part.live = piece }
        speechText[segment] = part
        if activeSpeechSegment == segment { heard(stitchTranscript(part.base, part.done + part.live)) }
    }

    func rolloverSpeech(listeningID: Int) {
        guard dictating, engine.isRunning, nextAnalyzer == nil, self.listenID == listeningID else { return }
        let next = beginSpeechSegment(text, listeningID: listeningID)
        nextFeed = next.feed; nextSpeechInputID = next.inputID; nextAnalyzer = next.analyzer
        nextReading = next.reading; nextSpeechSegment = next.segment
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in
            guard let self, self.listenID == listeningID, engine.isRunning,
                  let nextFeed, let nextSpeechInputID, let nextAnalyzer, let nextReading else { return }
            let oldAnalyzer = analyzer, oldReading = reading, oldSegment = activeSpeechSegment
            if let oldID = speechInputID { speechInputs?.finish(oldID) }
            if var part = speechText[nextSpeechSegment] { part.base = text; speechText[nextSpeechSegment] = part }
            feed = nextFeed; speechInputID = nextSpeechInputID; analyzer = nextAnalyzer; reading = nextReading
            activeSpeechSegment = nextSpeechSegment
            self.nextFeed = nil; self.nextSpeechInputID = nil; self.nextAnalyzer = nil; self.nextReading = nil; self.nextSpeechSegment = 0
            if let part = speechText[activeSpeechSegment] { heard(stitchTranscript(part.base, part.done + part.live)) }
            Task {
                try? await oldAnalyzer?.finalizeAndFinishThroughEndOfInput()
                await oldReading?.value
                await MainActor.run { self.speechText.removeValue(forKey: oldSegment) }
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { Task { await oldAnalyzer?.cancelAndFinishNow() } }
        }
    }

    func start(dictate: Bool) {
        if dictate && !AXIsProcessTrusted() {
            pill(true); show()
            js("dictated", ["text": "Allow Accessibility in System Settings → Privacy & Security → Accessibility", "ok": false])
            hide(after: 6); return
        }
        drawingReply = !dictate && drawing.active
        let replying = drawingReply || retryOffer && !askFile.isEmpty
        replyAgent = dictate || (retryOffer && !askFile.isEmpty) ? "" : agentCard
        if !replying { if !dictate && !drawing.hasInput { drawing.clear() }; mini.reset(); try? FileManager.default.removeItem(atPath: focusFile) }   // a new ask: "show it" from the last one no longer counts
        guard !Prefs.bool("paused") else { dictating = false; return }
        dictating = dictate
        unpoint(false)   // a new ask replaces the held answer; do not schedule that old answer's delayed hide
        shush()
        if drawingReply { hush(keepReply: true); drawing.hold() }
        dictating = dictate   // hush invalidates the previous listen before this one starts
        if engine.isRunning { return dismiss() }   // the shortcut stops click-to-talk
        if busy && !replying {   // pressed again while it works = cancel
            return cancel()
        }
        cancelFast(); noteHidden()
        if dictate {
            dictateCleanup = Prefs.str("dictateMode") == "cleanup"
            dictateFellBack = false; dictateTimedOut = false
            captureDictationSelection(); replacement = nil
            if dictateCleanup { warmDictationCleanup() }
        } else if replying { offerText = text } else { captureSelection(); replacement = nil }
        if !dictate && !drawingReply { targetScreen = currentRequestScreen(panel) }   // a guide may have moved the box to another display
        text = ""; ahead = ""; speechFailed = false; consumed = 0; consumedText = ""; liveRevised = false; did = []
        if !panel.isVisible && Date().timeIntervalSince(lastDone) > 300 { js("reset"); try? FileManager.default.removeItem(atPath: recent) }
        pill(dictate)
        if !dictate {
            if !replying && Prefs.str("input") == "type" && !clickTalk {   // Settings: the shortcut opens the box ready to type
                if composing && panel.isVisible { return dismiss() }   // pressed again = put it away
                unwarm(); warm = spawn()
                onboarding.tried(); show()
                panel.makeKey(); panel.makeFirstResponder(web); js("compose", true)
                return
            }
        }
        toggleTalk = !clickTalk && !dictate && Prefs.str("talkMode") == "toggle"   // dictation locks with a double tap instead
        cue("soundStart")
        if !dictate && (!replying || drawingReply) { unwarm(); warm = spawn() }
        hovering = false
        if dictate { js("listen", "dict") }
        else if replying && !drawingReply { js("draft", "") } else { js("listen"); if let s = selection { js("selected", s.text) } }   // talking about a drawing still shows the listening orb
        show()
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            if replying { stopOfferInput() } else { hush() }; js("msg", "Allow Rabik in System Settings → Privacy & Security → Microphone."); hide(after: 6); return
        }
        guard dictate || SFSpeechRecognizer.authorizationStatus() == .authorized else {
            if replying { stopOfferInput() } else { hush() }; js("msg", "Allow Rabik in System Settings → Privacy & Security → Speech Recognition."); hide(after: 6); return
        }
        guard let device = listenMic().flatMap({ AVCaptureDevice(uniqueID: $0.uid) }) ?? AVCaptureDevice.default(for: .audio) else {
            if replying { stopOfferInput() } else { hush() }; js("msg", "No microphone is available. Connect one and try again."); hide(after: 6); return
        }
        if !dictate && !replying && onboarding.win == nil && Prefs.bool("tips") && !Prefs.bool("pointCoached") { Prefs.set("pointCoached", true); js("pointCoach", true) }   // the first ask after setup (mic and speech allowed): one look at the Point button
        onboarding.tried()
        quietAudio.begin(Prefs.bool("quietAudio"), level: Float32(Prefs.num("quietLevel")))
        listenID += 1; let listeningID = listenID; began = Date()   // key-down until the mic is ready; a release in that gap is a tap
        speechInputs = SpeechInputs(); speechText = [:]; speechSegment = 0; nextSpeechRollover = 50
        let first = beginSpeechSegment("", listeningID: listeningID)
        feed = first.feed; speechInputID = first.inputID; analyzer = first.analyzer; reading = first.reading; activeSpeechSegment = first.segment
        let want = speechFormat ?? AVAudioFormat(standardFormatWithSampleRate: 16000, channels: 1)!
        var conv: AVAudioConverter?, convFrom: AVAudioFormat?
        var n = 0
        let onBuffer: (AVAudioPCMBuffer) -> Void = { [weak self] buf in
            if buf.format != want, convFrom != buf.format { conv = AVAudioConverter(from: buf.format, to: want); convFrom = buf.format }
            if buf.format != want, let conv, let out = AVAudioPCMBuffer(pcmFormat: want, frameCapacity: AVAudioFrameCount(Double(buf.frameLength) * want.sampleRate / buf.format.sampleRate) + 1) {
                var given = false
                conv.convert(to: out, error: nil) { _, status in
                    if given { status.pointee = .noDataNow; return nil }
                    given = true; status.pointee = .haveData; return buf
                }
                self?.speechInputs?.yield(AnalyzerInput(buffer: out))
            } else {
                self?.speechInputs?.yield(AnalyzerInput(buffer: buf))
            }
            n += 1
            guard n % 2 == 0, let ch = buf.floatChannelData?[0], buf.frameLength > 0 else { return }
            var sum: Float = 0
            for i in 0..<Int(buf.frameLength) { sum += ch[i] * ch[i] }
            let v = Double(min(1, sqrt(sum / Float(buf.frameLength)) * 14))
            DispatchQueue.main.async { if self?.listenID == listeningID, self?.engine.isRunning == true { self?.js("level", v) } }
        }
        engine.start(device, sampleRate: want.sampleRate, onBuffer) { [weak self] result in
            guard let self, listenID == listeningID else { return }
            if case .failure(let error) = result { if replying { stopOfferInput() } else { hush() }; js("msg", "Mic error: \(error.localizedDescription)"); hide(after: 3); return }
            began = Date()   // measure the limit from when the mic is ready
            Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] t in
                guard let self, listenID == listeningID, engine.isRunning else { return t.invalidate() }
                let f = (dictating ? dictateHotkey() : hotkey()).flags, held = Date().timeIntervalSince(began)
                if clickTalk && text.isEmpty && held > 8 { t.invalidate(); if offerText != nil { stopOfferInput(); return }; hush(); js("stopped", ""); return hide(after: 3) }   // nothing said: stop the mic quietly
                if dictating && held >= nextSpeechRollover { nextSpeechRollover += 50; rolloverSpeech(listeningID: listeningID) }
                if !dictating && held > 60 { t.invalidate(); recordingLimit(); return }
                if !toggleTalk && !clickTalk && !f.isEmpty && !NSEvent.modifierFlags.isSuperset(of: f) { if dictating { dictateShortcut(false) } else { t.invalidate(); stop() } }
            }
        }
    }

    func heard(_ now: String) {
        guard engine.isRunning || busy else { return }
        text = now
        if dictating { scheduleDictateAhead(); return }   // cleanup starts on a pause; the pill still shows only the wave
        if offerText != nil {
            js(drawingReply ? "words" : "draft", now)
            if clickTalk { quiet?.cancel(); let q = DispatchWorkItem { [weak self] in self?.stop() }; quiet = q; DispatchQueue.main.asyncAfter(deadline: .now() + 1.3, execute: q) }
            return   // card replies never enter live commands or early AI thinking
        }
        js("words", text)
        if consumed > 0 && transcriptKey(words().prefix(consumed).joined(separator: " ")) != consumedText { liveRevised = true }
        if Prefs.bool("live") {   // instant commands (open, move, search, play) run mid-sentence; the AI still waits for confirmed words
            pause?.cancel()   // only after a pause: "search amazon" mid-word is the start of "search amazon for e-bikes"
            let item = DispatchWorkItem { [weak self] in self?.tryFast() }
            pause = item
            DispatchQueue.main.asyncAfter(deadline: .now() + Prefs.num("aheadDelay"), execute: item)
        }
        if clickTalk {   // no keys to let go of: a 1.3 s pause ends it
            quiet?.cancel(); let q = DispatchWorkItem { [weak self] in self?.stop() }; quiet = q
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.3, execute: q)
        }
        if !ahead.isEmpty && transcriptKey(rest()) != transcriptKey(ahead) { dropAhead() }   // the user kept talking: that start was for half a sentence
        aheadItem?.cancel()   // a longer pause = the user is probably done: start the AI now, keys still held
        guard Prefs.bool("ahead") else { return }
        let go = DispatchWorkItem { [weak self] in self?.startAhead() }
        aheadItem = go
        DispatchQueue.main.asyncAfter(deadline: .now() + Prefs.num("aheadDelay"), execute: go)
    }

    func scheduleDictateAhead() {
        dictateAheadItem?.cancel()
        guard dictateCleanup, engine.isRunning else { return }
        let go = DispatchWorkItem { [weak self] in
            guard self?.engine.isRunning == true else { return }
            self?.startDictateAhead(early: true)
        }
        dictateAheadItem = go
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4, execute: go)
    }

    func words() -> [Substring] { text.split(separator: " ") }
    func rest() -> String { let w = words(); return w.count > consumed ? w[consumed...].joined(separator: " ") : "" }

    func startAhead() {
        if drawing.hasInput || pointContext != nil { return }   // the marked crop belongs to the confirmed request, not a discarded speculative start
        if engine.isRunning && selectionPending {
            let item = DispatchWorkItem { [weak self] in self?.startAhead() }; aheadItem = item
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05, execute: item); return
        }
        let r = rest()
        guard engine.isRunning, !selectionPending, !fastBusy, !liveRevised, !r.isEmpty, transcriptKey(r) != transcriptKey(ahead) else { return }
        let core = r.lowercased().replacingOccurrences(of: #"^(?:(?:hey|ok|okay|rabik|please|can you|could you|would you|also|and|now|then)[,\s]+)+"#, with: "", options: .regularExpression)
        if ["open", "launch", "start", "pull up", "bring up", "focus", "switch to", "go to", "snap", "move", "put", "throw", "send", "make", "play", "search", "google", "look up"].contains(where: { core.hasPrefix($0 + " ") }) || hints.contains(where: { transcriptKey($0) == transcriptKey(r) }) { return }
        dropAhead()
        ahead = r
        run(r, speculative: true)
        warm = spawn()   // ready again in case the user keeps talking
    }

    // Runs `rabik.py --fast` on the words not yet used; exit 0 means it was a simple command and it is done.
    func cancelFast() { fastProc?.terminate(); fastProc = nil; fastBusy = false }

    func tryFast() {
        let w = words()
        guard Prefs.bool("live"), Prefs.bool("instant"), engine.isRunning, !drawing.hasInput, !fastBusy, !liveRevised, w.count > consumed else { return }
        let seg = w[consumed...].joined(separator: " "), n = w.count, prefix = transcriptKey(w.joined(separator: " "))
        let p = py(["--fast", seg], ["RABIK_FRONT": mine, "RABIK_SCREEN": targetScreen, "RABIK_LIVE": "1", "RABIK_FOCUS_GUARD": "1"]), out = Pipe()
        p.standardOutput = out
        do { try p.run() } catch { return }
        fastProc = p
        fastBusy = true
        DispatchQueue.global().async { [weak self] in
            let line = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            p.waitUntilExit()
            DispatchQueue.main.async { [weak self] in
                guard let self, fastProc === p else { return }
                fastProc = nil; fastBusy = false
                if p.terminationStatus == 0 && line.hasPrefix("✓") {
                    consumed = n; consumedText = prefix
                    if transcriptKey(words().prefix(n).joined(separator: " ")) != prefix { liveRevised = true }
                    did.append(String(line.dropFirst(2)))
                    js("line", "▸ " + line.dropFirst(2))
                }
            }
        }
    }

    func dropAhead() {
        if !ahead.isEmpty { proc?.terminate(); proc = nil; ahead = ""; if engine.isRunning { busy = false } }
    }

    func stop() {
        guard engine.isRunning, !clickTalk || text.isEmpty == false else { return }
        let inputs = speechInputs
        if dictating { dictateSeconds = Date().timeIntervalSince(began); dictateReleased = Date(); startDictateAhead() }   // cleanup runs while the last words finalize
        engine.stop { inputs?.finishAll() }
        quietAudio.end()
        clickTalk = false; toggleTalk = false; quiet?.cancel()
        busy = true
        if dictating { cue("soundRelease"); js("finishing", dictateCleanup ? "Cleaning up…" : "") }
        else if offerText == nil { js("think") }   // card replies keep the response clock paused
        let an = analyzer, rd = reading, next = nextAnalyzer
        nextReading?.cancel(); nextFeed = nil; nextAnalyzer = nil; nextReading = nil; nextSpeechInputID = nil; nextSpeechSegment = 0
        Task { await next?.cancelAndFinishNow() }
        stops += 1
        let g = stops
        let once: (Bool) -> Void = { [weak self] confirmed in
            guard let self, g == stops else { return }
            stops += 1; listenID += 1; pause?.cancel()
            if confirmed || dictating && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { dictating ? finishDictation() : finish() }
            else {
                if let old = offerText { let partial = text; text = old; offerText = nil; busy = proc?.isRunning == true; js("draft", partial); return }   // a drawing reply has no worker; a card's keeps waiting
                if dictating { hush(); cue("soundStop"); return hide(after: 0.2) }
                if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { hush(); js("msg", ""); return hide(after: 0.2) }   // nothing to review
                review("Couldn’t confirm your words. Check them and press Return.")
            }
        }
        Task {   // let the model finish the last words, then act
            guard let an else { return await MainActor.run { once(false) } }
            do {
                try await an.finalizeAndFinishThroughEndOfInput()
                await rd?.value
                await MainActor.run { once(!speechFailed) }
            } catch { await MainActor.run { once(false) } }
        }
        // Finalizing can hang: offer the partial transcript for review instead of executing it. Dictation shares this wait:
        // a shorter one inserts its volatile words before the final result.
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self, g == stops else { return }
            rd?.cancel(); Task { await an?.cancelAndFinishNow() }
            once(false)
        }
    }

    // Replace / Delete / Insert: the text goes to the saved selection, or for a draft to the saved cursor.
    func applyReplacement() {
        guard let draft = replacement, !replacing else { return }
        guard Prefs.bool("selection"), let selection, mode != "draft" || selection.caret else { js("replaced", false); return }
        replacing = true; let id = selectionID
        selection.apply(mode == "delete" ? "" : draft, valid: { [weak self] in
            self?.selectionID == id && self?.replacing == true && Prefs.bool("selection") && !Prefs.bool("paused")
        }) { [weak self] ok in
            guard let self, selectionID == id else { return }
            replacing = false
            if ok { replacement = nil; self.selection = nil }
            js("replaced", ok)
        }
    }

    var correctionTimer: Timer?, learnedWord: String?, dictationAppName = "App", dictateSeconds = 0.0, lastDictation: String?
    var dictateFellBack = false, dictateTimedOut = false
    @discardableResult func saveDictation(_ value: String, appName: String) -> Bool {
        let saved = DictationData.record(value, raw: text.trimmingCharacters(in: .whitespacesAndNewlines), app: appName, seconds: dictateSeconds > 0 ? dictateSeconds : Date().timeIntervalSince(began))
        if !saved { js("dictated", ["text": "Your words are ready. Couldn’t save history or stats.", "ok": false]) }
        Rabik.settings.send("dictation", DictationData.state())
        return saved
    }
    func prepareDictation(_ value: String, target: TextSelection) -> () -> Void {
        let before = axAttribute(target.element, kAXSubroleAttribute) as? String == kAXSecureTextFieldSubrole ? nil : target.value
        let range = target.range
        return { [weak self] in
            guard let self else { return }
            lastDictation = value
            saveDictation(value, appName: target.app.localizedName ?? "App")
            stopReplay()
            guard Prefs.bool("dictateLearn"), axAttribute(target.element, kAXSubroleAttribute) as? String != kAXSecureTextFieldSubrole else { return }
            let readable = before.flatMap { before -> (String, String)? in
                guard let range, range.location >= 0, range.length >= 0, range.location + range.length <= (before as NSString).length else { return nil }
                let prefix = (before as NSString).substring(to: range.location)
                let suffix = (before as NSString).substring(from: range.location + range.length)
                return target.value == prefix + value + suffix ? (prefix, suffix) : nil
            }
            guard let readable else { NSLog("Dictation learning: field unreadable, watching keys"); return replayEdits(value, app: target.app) }
            NSLog("Dictation learning: watching the field")
            let (prefix, suffix) = readable, deadline = Date().addingTimeInterval(20), id = dictateID
            var last = value, changed = Date()
            correctionTimer = Timer.scheduledTimer(withTimeInterval: 0.35, repeats: true) { [weak self] timer in
                guard let self, Date() < deadline, dictateID == id, !engine.isRunning, !busy,
                      Prefs.bool("dictateLearn"), !Prefs.bool("paused"), NSWorkspace.shared.frontmostApplication == target.app,
                      let focused = axAttribute(AXUIElementCreateApplication(target.app.processIdentifier), kAXFocusedUIElementAttribute),
                      CFEqual(focused, target.focus),
                      axAttribute(target.element, kAXSubroleAttribute) as? String != kAXSecureTextFieldSubrole,
                      let current = target.value, current.count <= 100000,
                      current.hasPrefix(prefix), current.hasSuffix(suffix), current.count >= prefix.count + suffix.count else { timer.invalidate(); return }
                let span = String(current.dropFirst(prefix.count).dropLast(suffix.count))
                if span != last { last = span; changed = Date(); return }
                guard Date().timeIntervalSince(changed) > 2, learnFix(value, span) else { return }
                timer.invalidate()
            }
        }
    }
    @discardableResult func learnFix(_ value: String, _ edited: String) -> Bool {
        guard let fix = DictationData.correction(value, edited), !DictationData.words.contains(fix.word) else { return false }
        let word = fix.word
        guard DictationData.word(word) else { return false }
        DictationData.fix(fix.heard, word)
        learnedWord = word; pill(true); show(); js("learned", word); hide(after: 6)
        Rabik.settings.send("dictation", DictationData.state())
        return true
    }
    // No readable field: the next keys in that app, held in memory only, for 20 s; a click, secure input or another app ends it.
    var editKeys: Any?, replayIdle: Timer?
    func replayEdits(_ value: String, app: NSRunningApplication) {
        var replay = DictationData.Replay(value), keys = 0, learned = false
        let id = dictateID
        let check = { [weak self] in
            guard let self, !learned, replay.text != value, learnFix(value, replay.text) else { return }
            learned = true; NSLog("Dictation learning (keys): learned after %d keys", keys); stopReplay()
        }
        // Why learning ended, never the words: app.err, for "nothing was learned".
        let end = { [weak self] (why: String) in
            check()
            if !learned { NSLog("Dictation learning (keys): %@ after %d keys, %@", why, keys, replay.text == value ? "no edit" : "not a spelling fix") }
            self?.stopReplay()
        }
        correctionTimer = Timer.scheduledTimer(withTimeInterval: 20, repeats: false) { _ in end("20 s passed") }
        editKeys = NSEvent.addGlobalMonitorForEvents(matching: [.keyDown, .leftMouseDown]) { [weak self] e in
            guard let self else { return }
            let f = e.modifierFlags
            let why = dictateID != id ? "next dictation" : engine.isRunning || busy ? "Rabik busy" : !Prefs.bool("dictateLearn") || Prefs.bool("paused") ? "off" :
                NSWorkspace.shared.frontmostApplication != app ? "app changed" : IsSecureEventInputEnabled() ? "secure input" : e.type != .keyDown ? "click" : nil
            guard why == nil, replay.key(Int(e.keyCode), e.characters ?? "", option: f.contains(.option), control: f.contains(.control), command: f.contains(.command)) else {
                return end(why ?? "key \(e.keyCode)")   // Return after a fix still learns it
            }
            keys += 1
            replayIdle?.invalidate()
            replayIdle = Timer.scheduledTimer(withTimeInterval: 2, repeats: false) { _ in check() }   // a shorter pause can land mid-word: "Saart"
        }
    }
    func stopReplay() {
        correctionTimer?.invalidate(); replayIdle?.invalidate()
        if let editKeys { NSEvent.removeMonitor(editKeys) }
        editKeys = nil
    }

    // ⌃⌘V, like Willow Voice: the last dictation goes in at the cursor wherever it is now; the user's clipboard comes back after.
    func pasteLastDictation(_ tries: Int = 0) {
        if NSEvent.modifierFlags.contains(.control) && tries < 50 {   // ⌃ still held from the shortcut turns ⌘V into ⌃⌘V in apps that read live modifiers
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.02) { [weak self] in self?.pasteLastDictation(tries + 1) }; return
        }
        guard !Prefs.bool("paused"), !dictating, let value = lastDictation ?? DictationData.archive.history.first?.text, !value.isEmpty,
              let clipboard = try? Hands.lease("clipboard.lock", wait: false) else { NSSound.beep(); return }
        guard let restore = borrowPasteboard(value) else { Hands.unlock(clipboard); NSSound.beep(); return }
        let front = NSWorkspace.shared.frontmostApplication
        for down in [true, false] {
            guard let e = CGEvent(keyboardEventSource: nil, virtualKey: 9, keyDown: down) else { continue }
            e.flags = .maskCommand
            if NSApp.keyWindow == nil || front == nil || front == .current { e.post(tap: .cghidEventTap) } else { e.postToPid(front!.processIdentifier) }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { restore(); Hands.unlock(clipboard) }
    }

    func stopDictationCleanup() {
        stopDictationWorker()
        dictateAheadItem?.cancel(); dictateAheadItem = nil
        dictateRun?.process.terminate(); dictateRun = nil; dictateAheadRuns = 0
    }

    // One transcript handed to a cleanup worker. key is its words only, so final words that match reuse a run started early.
    final class DictationCleanup {
        let key: String, process: Process
        var result: String??, done: ((String?) -> Void)?
        init(_ key: String, _ process: Process) { self.key = key; self.process = process }
        func finish(_ value: String?) { result = .some(value); done?(value) }
        func then(_ f: @escaping (String?) -> Void) { if let result { f(result) } else { done = f } }
    }
    var dictateRun: DictationCleanup?, dictateAheadItem: DispatchWorkItem?, dictateReleased = Date(), dictateAheadRuns = 0
    static func dictationKey(_ s: String) -> String {
        s.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted).filter { !$0.isEmpty }.joined(separator: " ")
    }
    static func dictationChangedMeaningfully(_ old: String, _ new: String) -> Bool {
        Array(new.split(separator: " ")).difference(from: old.split(separator: " ")).count >= 3
    }

    func stopDictationWorker() {
        try? dictateInput?.close()
        dictateProcess?.terminate()
        dictateProcess = nil; dictateInput = nil; dictateOutput = nil
    }

    // The warm worker takes one transcript; nil when none could start.
    func sendDictationCleanup(_ source: String) -> DictationCleanup? {
        if dictateProcess?.isRunning != true { warmDictationCleanup() }
        guard let p = dictateProcess, let input = dictateInput, let output = dictateOutput else { return nil }
        dictateProcess = nil; dictateInput = nil; dictateOutput = nil
        do {
            try input.write(contentsOf: Data((dictateBefore + "\u{0}" + source).utf8))
            try input.close()
        } catch { p.terminate(); return nil }
        let run = DictationCleanup(Self.dictationKey(source), p)
        DispatchQueue.global().async {
            // The worker closes its output before it stops Claude, so this returns without waiting for the exit.
            let cleaned = String(data: output.readDataToEndOfFile(), encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            DispatchQueue.main.async { run.finish(cleaned.isEmpty ? nil : cleaned) }
        }
        return run
    }

    // At most two pause runs; key-up always gets the warm spare, then final speech can use one last run if it changed.
    func startDictateAhead(early: Bool = false) {
        if !early { dictateAheadItem?.cancel(); dictateAheadItem = nil }
        let source = text.trimmingCharacters(in: .whitespacesAndNewlines), key = Self.dictationKey(source)
        guard dictating, dictateCleanup, !dictateSelectionPending, !early || dictateAheadRuns < 2,
              key.split(separator: " ").count >= 3, key != dictateRun?.key else { return }
        if early {
            if let run = dictateRun, run.result == nil && !Self.dictationChangedMeaningfully(run.key, key) { return }
        }
        guard
              let run = sendDictationCleanup(source) else { return }
        dictateRun?.process.terminate()
        dictateRun = run
        dictateAheadRuns += 1
        warmDictationCleanup()   // final speech words may still revise after key-up
    }

    func warmDictationCleanup() {
        stopDictationWorker()
        let p = py(["--dictate-cleanup-wait"]), input = Pipe(), output = Pipe()
        p.standardInput = input; p.standardOutput = output
        fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        do {
            try p.run()
            dictateProcess = p
            dictateInput = input.fileHandleForWriting
            dictateOutput = output.fileHandleForReading
        } catch {
            stopDictationWorker()
        }
    }

    func finishDictation() {
        if dictateSelectionPending {
            let id = dictateID
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self] in
                if self?.dictateID == id { self?.finishDictation() }
            }
            return
        }
        if dictateSelection == nil, !dictateSelectionRetried, let app = dictationTargetApp,
           NSWorkspace.shared.frontmostApplication == app {
            dictateSelectionRetried = true
            captureDictationSelection(retry: true)   // lazy AX can miss at key-down; try the same app once more before giving up
            let id = dictateID
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in   // a slow app gets 1 s, then the words go on (History when there is no box)
                guard let self, dictateID == id, dictateSelectionPending else { return }
                dictateSelectionPending = false; finishDictation()
            }
            return
        }
        let spoken = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let source = spoken
        guard !source.isEmpty else {
            stopDictationCleanup()
            busy = false; dictating = false; cue("soundStop"); hide(after: 0.2)
            return
        }
        if !dictateCleanup { return insertDictation(source) }
        let early = dictateRun?.key == Self.dictationKey(source)
        if !early { dictateRun?.process.terminate(); dictateRun = sendDictationCleanup(source) }
        stopDictationWorker()
        guard let run = dictateRun else { dictateFellBack = true; return insertDictation(source) }   // cleanup could not start: the heard words still go in
        let id = dictateID
        run.then { [weak self] cleaned in
            guard let self, dictateID == id, dictateRun === run else { return }
            dictateRun = nil
            dictateFellBack = cleaned == nil
            NSLog("Dictation cleanup: %.2f s after key-up%@", Date().timeIntervalSince(dictateReleased), early ? " (started early)" : "")
            insertDictation(cleaned ?? source)
        }
        // A cleanup that hangs (offline, Claude retrying) never holds the words: 8 s (a cold worker can take 3-5 s) plus time for long text, then the heard words go in.
        let limit = 8 + Double(source.split(separator: " ").count) / 50
        DispatchQueue.main.asyncAfter(deadline: .now() + limit) { [weak self] in
            guard let self, dictateID == id, dictateRun === run else { return }
            NSLog("Dictation cleanup: no answer in %.1f s, inserting the heard words", limit)
            dictateFellBack = true; dictateTimedOut = true
            dictateRun = nil; run.process.terminate()
            insertDictation(source)
        }
    }

    func recordDictationEvent(_ insert: String) {
        telemetry(["dictation", dictateCleanup ? "cleanup" : "verbatim",
                   String(max(0, Date().timeIntervalSince(dictateReleased))),
                   dictateCleanup && !dictateFellBack ? "1" : "0",
                   dictateFellBack ? "1" : "0", dictateTimedOut ? "1" : "0", insert])
    }

    func dictationDeliveryFailed(_ value: String) {
        let failed = dictateSelection == nil ? "No text field." : "Couldn’t insert."
        recordDictationEvent(dictateSelection == nil ? "no box" : "failed")
        busy = false; dictating = false; dictateSelection = nil; lastDictation = value
        let paste = pasteHotkeyRegistered ? " Press ⌃⌘V to paste it." : ""
        cue("soundStop")
        // Never the clipboard: the user's own copy stays. History keeps the words; with it off (or unsaved) they stay on screen.
        guard Prefs.bool("dictateHistory") && saveDictation(value, appName: dictationAppName) else {
            js("dictated", ["text": failed + (paste.isEmpty ? " Your words are still here." : paste), "ok": false, "words": value]); return
        }
        js("dictated", ["text": failed + (paste.isEmpty ? " Saved to History." : paste), "ok": false, "history": true]); hide(after: 6)
    }

    func insertDictation(_ heard: String) {
        let value = DictationData.fixed(heard)
        guard let target = dictateSelection else {
            dictationDeliveryFailed(value); return
        }
        let id = dictateID, inserted = prepareDictation(value, target: target)
        target.apply(value, preserveFocus: true, valid: { [weak self] in
            self?.dictateID == id && self?.dictating == true && !Prefs.bool("paused") &&
            NSWorkspace.shared.frontmostApplication == target.app
        }) { [weak self] ok in
            guard let self, dictateID == id else { return }
            if !ok { dictationDeliveryFailed(value); return }
            recordDictationEvent("ok")
            busy = false; dictating = false; dictateSelection = nil
            cue("soundDone"); js("dictated", ["text": "", "ok": true]); hide(after: 0.8); inserted()
        }
    }

    func typed(_ t: String, keep: Bool = false, heard: Bool = false) {   // the typing box (keep: it stays open for the next one; heard: spoken about a drawing, its turn already shows)
        if drawing.active {   // a follow-up keeps the drawing; only a new drawing replaces it
            if transcriptKey(t) == "next" { drawing.next(); return }
            drawing.hold()
            if busy { cancel() }
        }
        if retryOffer && !askFile.isEmpty { js("respond", t); return }
        guard !busy, !engine.isRunning else { return }
        if ["report feedback", "report a bug"].contains(transcriptKey(t)) { Rabik.settings.open(tab:"feedback"); return }
        if selectionPending {
            let id = selectionID
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self] in
                if self?.selectionID == id { self?.typed(t, keep: keep, heard: heard) }
            }
            return
        }
        if !panel.isKeyWindow { selection = TextSelection.capture() }
        if !Prefs.bool("selection") { selection = nil }
        if !drawing.active { targetScreen = currentRequestScreen(panel) }   // follow-ups stay with the guide, not its relocated box
        text = t; replacement = nil
        if !heard { replyAgent = agentCard }   // a spoken drawing reply keeps the done card captured at key-down
        if !heard { js("listen", keep); if let s = selection { js("selected", s.text) } }; show(); js("words", t); run(t)
    }

    func finish() {
        guard busy else { return }   // cancelled while the last words landed
        if let old = offerText {
            let response = text; text = old; offerText = nil
            if drawingReply {
                drawingReply = false
                if transcriptKey(response) == "next" { unwarm(); drawing.next(); busy = proc?.isRunning == true; return }
                hush(keepReply: false, keepWarm: true); typed(response, heard: true); return
            }
            js("respond", response); return
        }
        if fastBusy || selectionPending {
            let g = stops
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [self] in if g == stops { finish() } }; return
        }
        aheadItem?.cancel()
        if liveRevised {
            hush(); js("msg", "Your words changed after Rabik acted. Check them, then press Return.")
            pinned = true; panel.makeKey(); panel.makeFirstResponder(web); js("draft", text); return
        }
        let rest = rest()
        if did.isEmpty, !rest.isEmpty && transcriptKey(rest) == transcriptKey(ahead), proc?.isRunning == true {   // already started on exactly this while the user talked
            ahead = ""; unwarm()
            do { try "go".write(toFile: commit, atomically: true, encoding: .utf8) }
            catch { cancel(); js("msg", "Could not confirm the request. Please try again.") }
            return
        }
        dropAhead()
        // the rest keeps the whole sentence: "for e-bikes, open the cheapest" alone lost "on Amazon"
        if !rest.isEmpty { return run(did.isEmpty ? rest : text, remaining: did.isEmpty ? nil : rest) }
        busy = false; guardUntil = Date().addingTimeInterval(2); unwarm()   // nothing left for the AI; an app an instant command started can still jump forward
        if did.isEmpty { js("msg", ""); return hide(after: 0.2) }   // nothing heard: end quietly, no error line
        answer = "✓ " + did.joined(separator: " ")
        deliver(did.joined(separator: " "))
        js("line", answer); lastDone = Date(); cue("soundDone"); hide(after: linger(5))
    }

    // rabik.py --wait, started at key-down so Claude is up by the time the user lets go; run() hands it the words.
    func spawn() -> (p: Process, input: FileHandle, commit: String)? {
        let commit = NSTemporaryDirectory() + "rabik-commit-" + UUID().uuidString
        warmSel = selKey
        let p = py(["--wait"], ["RABIK_UI": "1", "RABIK_FRONT": mine, "RABIK_SCREEN": targetScreen, "RABIK_COMMIT": commit, "RABIK_SELECTION": warmSel == "\u{1}" ? "" : warmSel, "RABIK_CARET": warmSel == "\u{1}" ? "1" : "", "RABIK_FOCUS_GUARD": "1"])
        let pipe = Pipe(), inp = Pipe(); p.standardOutput = pipe; p.standardInput = inp
        fcntl(inp.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)   // a worker can exit before we write; let the catch handle EPIPE
        var buffer = Data(), guided = false   // guided: this ask put a guide on screen, whose callouts carry the explanation
        let feed = { [weak self] (d: Data) in
            DispatchQueue.main.async {
                guard let self, self.proc === p else { return }   // buffered output from a cancelled request stays cancelled
                buffer += d
                while let i = buffer.firstIndex(of: 10) {
                    let line = String(decoding: buffer[..<i], as: UTF8.self); buffer.removeSubrange(...i)
                    if line == "! setup" { onboarding.open(); continue }   // Claude not installed, signed out or no plan
                    if line == "! feedback" { Rabik.settings.open(tab:"feedback"); continue }
                    if line == "! improve" { self.js("improve"); continue }   // the one-time "help make Rabik better?" card
                    if line.hasPrefix("▣ "), let value = try? JSONSerialization.jsonObject(with:Data(line.dropFirst(2).utf8)) as? [String:Any] { if Prefs.d["miniScreen"] as? Bool ?? true { self.mini.receive(value) }; continue }
                    if line.hasPrefix("✎ ") {
                        if Prefs.bool("draw"), self.drawing.receive(Data(line.dropFirst(2).utf8)) {
                            self.shush(); guided = true
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in   // once the box has glided clear of the marks
                                guard let self, panel.isVisible, let m = drawing.focus else { return }
                                let top = NSScreen.screens.first?.frame.maxY ?? 0
                                lead(from: panel.frame, to: CGRect(x: m.minX, y: top - m.maxY, width: m.width, height: m.height))
                            }
                        }
                        else { self.js("line", line) }
                        continue
                    }
                    if line.hasPrefix("@ ") {   // "show me where": an answer's point leads from the box and stays; a click's spot goes to the mini screen if it is up
                        if line.hasSuffix(" answer") { pointAt(line, from: self.panel.isVisible ? self.panel.frame : nil, hold: self.linger(20)) { [weak self] in self?.hide(after: 3) } }
                        else if self.mini.target != nil { self.js("line",line) } else { pointAt(line) }
                        continue
                    }
                    if line.hasPrefix("? ") {   // safe mode: "? <question>\t<command>\t<answer file>"
                        let p = line.dropFirst(2).components(separatedBy: "\t")
                        guard (3...6).contains(p.count) else { continue }
                        self.retryOffer = p.count >= 5 && p[4] == "retry"
                        self.askNeed = p.count == 6 && !self.retryOffer ? (try? JSONSerialization.jsonObject(with:Data(p[5].utf8))) as? [String:Any] ?? [:] : [:]
                        self.askFile = p[2]; self.show(); self.js("ask", [p[0], p[1], self.retryOffer ? "retry" : "", self.retryOffer && p.count == 6 ? p[5] : ""]); continue
                    }
                    if line.hasPrefix("⚙ ") {   // "⚙ <key> <true|false>": the AI flips one of Rabik's switches; never pause, and Safe mode only on
                        let p = line.split(separator: " ").map(String.init)
                        if p.count == 3, Prefs.defaults[p[1]] is Bool, p[1] != "paused", p[1] != "safe" || p[2] == "true" { Rabik.settings.apply(p[1], p[2] == "true"); Rabik.settings.push() }
                        else if p.count == 3, Prefs.d[p[1]] is String, !p[1].hasPrefix("hotkey") { Rabik.settings.apply(p[1], p[2]); Rabik.settings.push() }   // a choice setting ("workIn front")
                        continue
                    }
                    if line.hasPrefix("◇ "), let j = try? JSONSerialization.jsonObject(with: Data(line.dropFirst(2).utf8)) as? [String: Any] {   // "which one?": the choices card
                        self.askNeed = [:]; self.askFile = j["a"] as? String ?? ""; self.show(); self.js("pick", j); continue
                    }
                    if line.hasPrefix("▤ ") { self.showAgent = String(line.dropFirst(2)); continue }
                    if line.hasPrefix("▦ ") { self.showRecap = String(line.dropFirst(2)); continue }
                    if line.hasPrefix("⇢ "), let value = try? JSONSerialization.jsonObject(with:Data(line.dropFirst(2).utf8)) as? [String:Any] {   // movable: ⌃⌥↩ moves it / {}: no longer movable
                        self.agentMoveFile = self.busy ? value["a"] as? String ?? "" : ""; continue
                    }
                    if line.hasPrefix("⤴ "), let brief = try? JSONSerialization.jsonObject(with: Data(line.dropFirst(2).utf8)) as? [String: Any] {
                        self.agentMoveFile = ""; self.busy = false; self.js("finished")
                        self.web.evaluateJavaScript("ui.moveSource()") { value, _ in
                            agentsUI.prepare(brief, from:(value as? [NSNumber])?.map(\.doubleValue))
                        }
                        continue
                    }
                    if line.hasPrefix("↺ ") {
                        guard let j = try? JSONSerialization.jsonObject(with: Data(line.dropFirst(2).utf8)) as? [String: Any], let draft = j["t"] as? String else { continue }
                        let now = j["mode"] as? String == "insert"   // the user asked to put it in: no Insert click needed
                        self.replacement = draft; self.mode = now ? "draft" : j["mode"] as? String ?? "replace"; self.pinned = true
                        let target = self.selection.map { ($0.editable || $0.pastable) && (self.mode != "draft" || $0.caret) } ?? false
                        self.js("rewrite", [draft, self.mode, target])
                        if self.mode == "draft" && target && (now || Prefs.str("draftInsert") == "auto") { self.applyReplacement() }
                        continue
                    }
                    if line.hasPrefix("✓") {
                        let result = self.replacement.flatMap { $0.isEmpty ? nil : $0 } ?? line.dropFirst(2).replacingOccurrences(of: "\u{2028}", with: "\n")
                        let finish = self.drawing.request?.steps.count == 1 ? "Done. It’s on your screen." : "Done. Steps are on screen."
                        self.mini.finish(); self.answer = "✓ " + (guided ? finish : result); self.deliver(guided ? finish : result, aloud: !guided)   // a guide's steps speak for themselves
                        self.js("line", self.answer); continue
                    }
                    if line.hasPrefix("! ") { self.js("msg", String(line.dropFirst(2))) }
                    else { self.js("line", line) }
                }
            }
        }
        pipe.fileHandleForReading.readabilityHandler = { feed($0.availableData) }
        p.terminationHandler = { [weak self] _ in
            pipe.fileHandleForReading.readabilityHandler = nil
            feed(pipe.fileHandleForReading.readDataToEndOfFile())   // the answer may still be in the pipe
            DispatchQueue.main.async {
                try? FileManager.default.removeItem(atPath: commit)
                guard let self, self.proc === p else { return }   // a cancelled run ending late must not touch the next one
                if !self.ahead.isEmpty { self.proc = nil; self.ahead = ""; self.busy = !self.engine.isRunning; return }
                if p.terminationStatus != 0 { telemetry(["error", "worker_exit", "python", String(p.terminationStatus)]) }
                self.busy = false; self.agentMoveFile = ""; self.guardUntil = Date().addingTimeInterval(2); self.proc = nil; self.mini.finish(); self.js("finished")   // Spotify jumps ~0.5 s after play returns
                self.lastDone = Date()
                if !self.answer.isEmpty { self.cue("soundDone") }
                if !self.showAgent.isEmpty { agentsUI.show(self.showAgent); self.showAgent = "" }
                if !self.showRecap.isEmpty { dailyRecap.open(self.showRecap); self.showRecap = "" }
                Apps.q.async { Apps.sync() }
                self.hide(after: self.linger(max(6, min(30, Double(self.answer.count) / 12))))   // longer answers stay longer
            }
        }
        do { try p.run() } catch { return nil }
        return (p, inp.fileHandleForWriting, commit)
    }

    func unwarm() { warm?.p.terminate(); warm = nil }

    func run(_ t: String, speculative: Bool = false, remaining: String? = nil) {
        let point = pointContext, drawn = drawing.summary
        pointContext = nil; unpoint(false)
        if point != nil { js("point", false) }   // the mark went with this ask (its picture is in the bubble): the chip must not wait for the next one
        drawing.clearInput(); drawing.deselect(); mini.reset(); if !busy && !engine.isRunning { noteHidden() }; busy = true; agentMoveFile = ""; answer = ""; showAgent = ""; showRecap = ""; try? FileManager.default.removeItem(atPath: focusFile)
        if !speculative { js("think") }
        if let w = warm, !w.p.isRunning { try? w.input.close(); warm = nil }
        if warm != nil && warmSel != selKey { unwarm() }   // spawned before the selection changed
        guard let w = warm ?? spawn() else {
            if let path = point?["image"] as? String { try? FileManager.default.removeItem(atPath:path) }
            busy = false
            if speculative { ahead = ""; return }
            telemetry(["error", "worker_exit", "python", "-1"])
            pinned = true; js("workerFailed"); show(); return
        }
        warm = nil; proc = w.p; commit = w.commit
        if !speculative {
            do { try "go".write(toFile: commit, atomically: true, encoding: .utf8) }
            catch { cancel(); js("msg", "Could not confirm the request. Please try again."); return }
        }
        do {
            var request: [String:Any] = ["front":mine, "task":t]
            if let remaining { request["remaining"] = remaining; request["done"] = did }
            if let point { request["point"] = point }
            if let drawn { request["drawing"] = drawn }
            if !replyAgent.isEmpty { request["agentCard"] = replyAgent }
            var data = try JSONSerialization.data(withJSONObject:request); data.append(10)
            try w.input.write(contentsOf:data); try w.input.close()
        } catch {
            if let path = point?["image"] as? String { try? FileManager.default.removeItem(atPath:path) }
            cancel(); js("msg", "The request worker stopped. Please try again.")
        }
    }
}
