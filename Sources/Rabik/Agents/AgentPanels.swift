// Background agents: their chips, cards and the Agent view. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

final class AgentPanels: NSObject, WKScriptMessageHandler {
    var process: Process?, input: FileHandle?, output: Pipe?, buffer = Data(), restarts = 0
    var shelf: ShelfPanel?, shelfWeb: WKWebView?, view: KeyPanel?, viewWeb: WKWebView?
    var startingLabel: NSTextField?, startingStep: NSTextField?
    let mini = MiniScreen()
    var rows: [String:[String:Any]] = [:], offers: [String:[String:Any]] = [:], named: [[String:Any]] = [], ready = Set<String>()
    var moveFrom: [String:[Double]] = [:], flying: [(String,[Double]?)] = []   // hand-offs (by handoffId) still waiting for their offer; accepted ones waiting for the rest of their ask
    var ping: String?, expandOnReady = "", nearSince: Date?   // ping: a done card the user asked for in the box
    var lastBox: NSDictionary?
    var hovered = "", miniSurface = "", selected = "", drag: (mouse:NSPoint, frame:NSRect)?
    var dismissed = Set(Prefs.d["agentDismissed"] as? [String] ?? []) {   // chips the user ×'d off the screen; their agents keep working in the badge and Agent view
        didSet { if dismissed != oldValue { Prefs.set("agentDismissed", dismissed.filter { rows[$0].map { Self.live.contains($0["status"] as? String ?? "") || Self.lingers($0) } ?? false }.sorted()) } }   // kept over a restart while it could still show
    }
    var monitor: Any?, keyMonitor: Any?, timer: Timer?, moves: [Any] = [], localKeys: Any?
    override init() {
        super.init()
        DispatchQueue.main.async { [weak self] in self?.start() }   // restore accepted work even if the user never opens Agents
        mini.forcePreview = true
        keyMonitor = NSEvent.addGlobalMonitorForEvents(matching:.keyDown) { [weak self] e in
            if ![kVK_Return,kVK_ANSI_KeypadEnter].contains(Int(e.keyCode)), !app.defaultKeys.isEmpty { app.defaultKey(false) }   // typing in another app: its Return is the user's again
            if Int(e.keyCode) == kVK_Escape { self?.js("shelf","blur") }   // the shelf never becomes key, so its page never sees Esc
        }
        localKeys = NSEvent.addLocalMonitorForEvents(matching:.keyDown) { [weak self] e in if Int(e.keyCode) == kVK_Escape { self?.js("shelf","blur") }; return e }
        timer = Timer.scheduledTimer(withTimeInterval:0.1, repeats:true) { [weak self] _ in self?.tick() }
        NotificationCenter.default.addObserver(forName:NSApplication.willTerminateNotification, object:nil, queue:.main) { [weak self] _ in
            self?.process?.terminate(); self?.mini.reset()
        }
        NotificationCenter.default.addObserver(forName:NSApplication.didChangeScreenParametersNotification, object:nil, queue:.main) { [weak self] _ in
            guard let self else { return }
            if let shelf, let screen = shelf.screen ?? NSScreen.main {
                let f = MeetingFrame.clamp(shelf.frame,screen.visibleFrame)
                shelf.setFrame(f,display:true)
            }
            if let view, let screen = view.screen ?? NSScreen.main { view.setFrame(MeetingFrame.clamp(view.frame,screen.visibleFrame),display:true) }
        }
        monitor = NSEvent.addLocalMonitorForEvents(matching:[.leftMouseDown,.leftMouseDragged,.leftMouseUp]) { [weak self] e in
            if e.type == .leftMouseDown, e.window !== self?.shelf { self?.js("shelf","blur") }   // a click in another Rabik window
            guard let self, let shelf, e.window === shelf else { return e }
            if e.type == .leftMouseDragged, let origin = drag {
                let point = NSEvent.mouseLocation
                var f = origin.frame; f.origin.x += point.x - origin.mouse.x; f.origin.y += point.y - origin.mouse.y
                let screen = NSScreen.screens.first { $0.frame.contains(point) } ?? shelf.screen ?? NSScreen.main!
                shelf.setFrame(MeetingFrame.clamp(f,screen.visibleFrame), display:true)
            } else if e.type == .leftMouseUp, drag != nil { drag = nil; remember() }
            return e
        }
        mini.publish = { [weak self] value in self?.js(self?.miniSurface ?? "shelf", "mini", value) }
    }
    func js(_ surface:String, _ call:String, _ value:Any = [:]) {
        let web = surface == "view" ? viewWeb : shelfWeb
        if ready.contains(surface) { callJS(web, "agents." + call, [value]) }
    }
    func send(_ data:[String:Any]) {
        start()
        guard let json = try? JSONSerialization.data(withJSONObject:data) else { return }
        do { try input?.write(contentsOf:json + Data([10])) }
        catch { process?.terminate() }
    }
    func start() {
        guard process == nil else { return }
        let p = py(["--agents"]), out = Pipe(), inp = Pipe(); p.standardOutput = out; p.standardInput = inp; p.standardError = FileHandle.nullDevice
        fcntl(inp.fileHandleForWriting.fileDescriptor,F_SETNOSIGPIPE,1)
        process = p; input = inp.fileHandleForWriting; output = out
        out.fileHandleForReading.readabilityHandler = { [weak self] file in
            let data = file.availableData
            DispatchQueue.main.async {
                guard let self, self.process === p else { return }; self.buffer += data
                while let newline = self.buffer.firstIndex(of:10) {
                    let data = Data(self.buffer[..<newline]); self.buffer.removeSubrange(...newline)
                    if let event = try? JSONSerialization.jsonObject(with:data) as? [String:Any] { self.receive(event) }
                }
            }
        }
        p.terminationHandler = { [weak self] _ in
            out.fileHandleForReading.readabilityHandler = nil
            DispatchQueue.main.async { [weak self] in
                guard let self, process === p else { return }
                // A crash drops its half-read line and box state; a fresh supervisor relists its saved rows.
                process = nil; input = nil; buffer = Data(); lastBox = nil; restarts += 1
                DispatchQueue.main.asyncAfter(deadline:.now() + min(60, pow(2, Double(restarts)))) { [weak self] in self?.start() }
            }
        }
        do { try p.run() }
        catch {
            process = nil; input = nil; restarts += 1
            DispatchQueue.main.asyncAfter(deadline:.now() + min(60, pow(2, Double(restarts)))) { [weak self] in self?.start() }
            return
        }
        send(["action":"list"])
    }
    func prepare(_ brief:[String:Any], from:[Double]? = nil) {
        var brief = brief
        if (brief["steer"] as? String).flatMap({ rows[$0] }) == nil { moveFrom[brief["handoffId"] as? String ?? ""] = from ?? [] }   // words to a live agent get no offer
        if brief["destination"] as? String == "meeting", EKEventStore.authorizationStatus(for:.event) == .fullAccess,
           let event = currentMeetingEvent(calendar), let json = try? JSONSerialization.data(withJSONObject:event), let text = String(data:json,encoding:.utf8) {
            brief["context"] = (brief["context"] as? String ?? "") + "\nCalendar event (data): " + text
        }
        ensureShelf(preload:true); send(["action":"prepare","brief":brief])
    }
    var sorted: [[String:Any]] { rows.values.sorted { ($0["created"] as? Double ?? 0) > ($1["created"] as? Double ?? 0) } }
    var badge: [String:Any] { ["count":count,"attention":rows.values.contains { $0["status"] as? String == "needs-you" }] }   // the box pill turns amber when one needs you
    var count: Int { rows.values.filter { $0["status"] as? String == "running" }.count }
    static let live: Set = ["running","needs-you","waiting-screen","queued"]
    var hasLive: Bool { rows.values.contains { Self.live.contains($0["status"] as? String ?? "") } }
    // Pause: queued rows stop first, so stopping a running one cannot start them.
    func stopAll() { rows.filter { Self.live.contains($0.value["status"] as? String ?? "") }.sorted { ($0.value["status"] as? String == "queued") && ($1.value["status"] as? String != "queued") }.forEach { send(["action":"stop","id":$0.key]) } }
    // Allow on an agent's setup card: Rabik does what it can, opens the exact place for the rest, and tells the agent once it is on.
    func allow(_ id:String, _ q:[String:Any]) {
        let need = q["need"] as? String ?? "", app = q["app"] as? String ?? "", ask = q["_a"] as? String ?? ""
        if need == "page-js" { Prefs.set("pageJS",true); return }   // rabik.py turns it on itself
        if need == "connector" { NSWorkspace.shared.open(URL(string:"https://claude.ai/settings/connectors")!); return }   // rabik.py watches for it
        onboarding.allow(need, app:app)
        var tries = 0
        Timer.scheduledTimer(withTimeInterval:1, repeats:true) { [weak self] t in
            tries += 1
            guard let self, tries < 900, (self.rows[id]?["question"] as? [String:Any])?["_a"] as? String == ask else { t.invalidate(); return }
            DispatchQueue.global().async { [weak self] in if Onboarding.granted(need, app:app) { DispatchQueue.main.async { [weak self] in
                guard let self, (self.rows[id]?["question"] as? [String:Any])?["_a"] as? String == ask else { t.invalidate(); return }
                t.invalidate(); self.send(["action":"granted","id":id])
            } } }
        }
    }
    func receive(_ event:[String:Any]) {
        let kind = event["event"] as? String ?? ""
        if kind == "list", let list = event["agents"] as? [[String:Any]] {
            restarts = 0
            rows = Dictionary(uniqueKeysWithValues:list.compactMap { row in (row["id"] as? String).map { ($0,row) } })
            named = event["named"] as? [[String:Any]] ?? []
            if !hovered.isEmpty, rows[hovered] == nil { endPreview() }
            if let ping, rows[ping] == nil { self.ping = nil; app.agentCard = ""; app.pinned = false; app.js("agentCancelled"); app.hide(after:1) }
            if rows.values.contains(where:Self.lingers) { ensureShelf(preload:true) }
            js("shelf","list",sorted); js("view","list",sorted); js("view","named",named)
        } else if kind == "named" {
            named = event["named"] as? [[String:Any]] ?? []; js("view","named",named)
            if let reply = event["reply"] as? String { js("view","namedReply",reply) }
        }
        if let row = event["agent"] as? [String:Any], let id = row["id"] as? String {
            let question = { (r:[String:Any]?) in (r?["question"] as? [String:Any])?["_a"] as? String }
            let asks = kind == "state" && row["status"] as? String == "needs-you" && question(row) != nil && question(row) != question(rows[id])
            let finished = Self.live.contains(rows[id]?["status"] as? String ?? "") && Self.lingers(row)
            rows[id] = row
            if asks, !quiet { app.sound("Ping",Float(Prefs.num("volume"))) }   // a new question from a working agent: it holds a slot until answered
            if row["status"] as? String == "needs-you" || finished { dismissed.remove(id) }   // a question, or a finish (news, as on the page), always comes back to the screen
            if kind == "state" {
                ensureShelf(preload:Self.lingers(row)); js("shelf","state",row); js("view","state",row)
                if hovered == id, let target = row["target"] as? [String:Any] { preview(id, surface:miniSurface, target:target) }
            } else if kind == "offer" {
                offers[id] = event["followup"] as? Bool == true ? row : [:]
                accept(id, from:moveFrom.removeValue(forKey:row["handoffId"] as? String ?? ""))
            } else if kind == "done" {
                if row["destination"] as? String == "meeting" { meeting.acceptAgent(row) }
                if quiet || row["routine"] != nil { notify(row); rows[id]?["notified"] = true; send(["action":"notified","id":id]) }
            } else if kind == "ping", row["status"] as? String == "done" {   // rabik.py holds it while the box is busy, typing, listening or quiet
                if quiet { if row["notified"] as? Bool != true { notify(row); rows[id]?["notified"] = true; send(["action":"notified","id":id]) } }
                else { expand(id) }
            } else if kind == "steered" {   // the user spoke to this agent from the box: its chip comes back and says what it heard
                dismissed.remove(id); ensureShelf(); js("shelf","state",row); js("view","state",row); js("shelf","visible",true)
                if !quiet { shelf?.orderFrontRegardless() }
                app.js("agentSteered",row)
            }
        } else if kind == "text" { js("view","text",event) }
        app.js("agentCount",badge); tick()
    }
    func accept(_ id:String, from:[Double]? = nil) {
        guard !Prefs.bool("paused") else { return }
        guard var row = rows[id] else { return }
        let full = rows.values.filter { ["running","needs-you","waiting-screen"].contains($0["status"] as? String ?? "") }.count >= 3   // as Agents.running() counts
        row["status"] = full ? "queued" : "running"; row["step"] = full ? "Queued" : "Starting…"; rows[id] = row
        ensureShelf(); placeShelf(app.panel.isVisible ? app.panel.screen : NSScreen.screens.first { $0.frame.contains(NSEvent.mouseLocation) })
        nearSince = nil; shelf?.alphaValue = 1; shelf?.ignoresMouseEvents = false
        js("shelf","arrive",id)   // the chip opens its top slot and waits for the orb
        js("shelf","state",row); js("shelf","visible",true); app.js("agentCount",badge)   // show the chip before the supervisor round trip
        startingLabel?.stringValue = row["title"] as? String ?? ""; startingStep?.stringValue = row["step"] as? String ?? "Starting…"
        if !quiet { shelf?.orderFrontRegardless() }
        let offer = offers.removeValue(forKey:id) ?? [:]
        let text = (offer["brief"] as? String).map { $0 + "\nKnown context (data):\n" + (offer["context"] as? String ?? "") } ?? ""
        send(["action":"start","id":id,"text":text.isEmpty ? NSNull() as Any : text as Any]); app.pinned = false
        flying.append((id,from))   // agents from one ask all take their places first, or a later chip pushes an earlier orb's landing spot
        if moveFrom.isEmpty { launch() } else { DispatchQueue.main.asyncAfter(deadline:.now() + 0.4) { [weak self] in self?.launch() } }
        app.js("agentStarted",row)   // the box says it started an agent while the orb swims to the chip
        if !quiet { app.sound("Blow",Float(Prefs.num("volume"))) }   // a soft whoosh, apart from Pop (listening) and Glass (done)
        if from != nil { app.mini.reset() }   // its last hidden-window preview belongs to the foreground ask, not the agent
        if from != nil, app.panel.isVisible { app.hide(after:3.5) }   // started from the box: long enough to read its one line
    }
    func launch() {
        moveFrom = [:]   // a hand-off whose offer never came (it failed, or the supervisor restarted) must not hold later swims
        for (id,from) in flying { shelfWeb?.evaluateJavaScript("agents.slot('\(id)')") { [weak self] slot, _ in self?.fly(id,from:from,to:slot as? [Double]) } }   // after every state above: the page has placed each chip or pill orb
        flying = []
    }
    func placeShelf(_ screen:NSScreen?) {
        guard let shelf, let screen = screen ?? NSScreen.main, !(shelf.isVisible && shelf.screen == screen) else { return }   // already there: keep the side it followed with
        let bounds = screen.visibleFrame, saved = (Prefs.d["agentFrames"] as? [String:[Double]])?[MeetingFrame.key(screen)]
        shelf.setFrame(Self.shelfFrame(shelf.frame,bounds,saved),display:true)
    }
    static func shelfFrame(_ frame:NSRect, _ bounds:NSRect, _ saved:[Double]?) -> NSRect {
        var f = frame; f.size.height = max(52,min(f.height,bounds.height))
        f.origin = NSPoint(x:bounds.maxX-f.width-12,y:bounds.maxY-f.height-8)
        if let saved, saved.count == 2, saved.allSatisfy(\.isFinite) { f.origin = NSPoint(x:saved[0],y:saved[1]-f.height) }
        return MeetingFrame.clamp(f,bounds)
    }
    // The shelf follows the pointer's display like the box, keeping its side and offsets.
    // An open chip, a drag or the orb's swim holds it.
    var following = false
    func follow() {
        guard let shelf, drag == nil, flight == nil, !following, pointerFollow(shelf.frame) != nil else { return }
        following = true
        shelfWeb?.evaluateJavaScript("agents.expanded()") { [weak self] open, _ in
            guard let self, let shelf = self.shelf else { return }
            self.following = false
            guard (open as? String ?? "").isEmpty || !shelf.isVisible, self.drag == nil, let f = pointerFollow(shelf.frame) else { return }
            shelf.setFrame(f,display:true)
        }
    }
    // The agent's orb lifts off the hand-off card and swims to the shelf's top slot: one transient panel, Core Animation only,
    // so nothing runs per frame in the app or WebKit. Reduce Motion (or no card) skips the swim; the chip cross-fades in.
    var flight: NSPanel?, flightPace = 1.0   // shortcut: pace > 1 is slow motion for VM frame captures only; nothing else sets it
    func fly(_ id:String, from rect:[Double]?, to slot:[Double]? = nil) {
        let land = { [weak self] in self?.js("shelf","land",id) }
        guard !quiet, !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion, let shelf, let rect, rect.count == 4, rect.allSatisfy(\.isFinite), rect[2] > 0, rect[3] > 0 else { land(); return }
        var r = NSRect(x:rect[0],y:rect[1],width:rect[2],height:rect[3])
        if !app.web.isFlipped { r.origin.y = app.web.bounds.height - r.maxY }
        let start = app.panel.convertToScreen(app.web.convert(r,to:nil)), from = NSPoint(x:start.midX,y:start.midY)
        let at = slot?.count == 2 && slot!.allSatisfy(\.isFinite) ? slot! : [24,26]   // page point of its orb; else the top chip's
        let to = NSPoint(x:shelf.frame.minX + at[0],y:shelf.frame.maxY - at[1])
        let lift = max(50,hypot(to.x - from.x,to.y - from.y) * 0.2)
        let frame = NSRect(x:min(from.x,to.x) - 60,y:min(from.y,to.y) - lift - 60,width:abs(to.x - from.x) + 120,height:abs(to.y - from.y) + lift + 120)
        let panel = ShelfPanel(contentRect:frame,styleMask:[.nonactivatingPanel,.borderless],backing:.buffered,defer:false)
        panel.isReleasedWhenClosed = false; panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false; panel.ignoresMouseEvents = true
        panel.level = .statusBar; applySharing(panel); panel.collectionBehavior = [.canJoinAllSpaces,.fullScreenAuxiliary,.ignoresCycle]
        let host = NSView(frame:NSRect(origin:.zero,size:frame.size)); host.wantsLayer = true; panel.contentView = host; host.layer?.speed = Float(1 / flightPace)
        let a = CGPoint(x:from.x - frame.minX,y:from.y - frame.minY), b = CGPoint(x:to.x - frame.minX,y:to.y - frame.minY), low = min(a.y,b.y) - lift
        let path = CGMutablePath(); path.move(to:a)   // a low swoop under both ends, then up into the slot
        path.addCurve(to:b,control1:CGPoint(x:a.x + (b.x - a.x) * 0.3,y:low),control2:CGPoint(x:a.x + (b.x - a.x) * 0.78,y:low + lift * 0.4))
        let blue = NSColor(srgbRed:0.04,green:0.52,blue:1,alpha:1).cgColor, begin = host.layer?.convertTime(CACurrentMediaTime(),from:nil) ?? 0, duration = 0.62
        func blob(_ size:CGFloat, _ opacity:Float, _ delay:Double, squash:Bool) {
            let orb = CAGradientLayer(); orb.type = .radial; orb.frame = CGRect(x:0,y:0,width:size,height:size); orb.cornerRadius = size / 2
            orb.colors = [CGColor(gray:1,alpha:1),blue,NSColor(srgbRed:0.04,green:0.52,blue:1,alpha:0).cgColor]; orb.locations = [0,0.45,1]
            orb.startPoint = CGPoint(x:0.5,y:0.5); orb.endPoint = CGPoint(x:1,y:1)
            orb.shadowColor = blue; orb.shadowRadius = size * 0.45; orb.shadowOpacity = 0.9; orb.shadowOffset = .zero; orb.position = a; orb.opacity = 0
            host.layer?.addSublayer(orb)
            let swim = CAKeyframeAnimation(keyPath:"position"); swim.path = path; swim.calculationMode = .paced; swim.rotationMode = .rotateAuto
            swim.timingFunction = CAMediaTimingFunction(controlPoints:0.5,0,0.2,1)
            let shape = CAKeyframeAnimation(keyPath:"transform")   // lift, stretch along the swim, squash on landing
            shape.values = squash ? [CATransform3DMakeScale(0.35,0.35,1),CATransform3DMakeScale(1.1,0.9,1),CATransform3DMakeScale(1.26,0.82,1),CATransform3DMakeScale(0.84,1.14,1),CATransform3DIdentity].map { NSValue(caTransform3D:$0) }
                                  : [CATransform3DMakeScale(0.5,0.5,1),CATransform3DIdentity,CATransform3DMakeScale(0.6,0.6,1)].map { NSValue(caTransform3D:$0) }
            shape.keyTimes = squash ? [0,0.15,0.5,0.88,1] : [0,0.4,1]
            let fade = CAKeyframeAnimation(keyPath:"opacity"); fade.values = [0,opacity,opacity,0]; fade.keyTimes = [0,0.1,0.86,1]
            let group = CAAnimationGroup(); group.animations = [swim,shape,fade]; group.duration = duration; group.beginTime = begin + delay
            group.fillMode = .both; group.isRemovedOnCompletion = false; orb.add(group,forKey:"swim")
        }
        for i in 1...5 { blob(CGFloat(20 - i * 2),Float(0.42 - Double(i) * 0.07),Double(i) * 0.035,squash:false) }   // the trailing glow
        blob(26,1,0,squash:true)
        flight = panel; panel.orderFrontRegardless()   // agents from one ask swim side by side; each panel orders itself out
        DispatchQueue.main.asyncAfter(deadline:.now() + (duration - 0.08) * flightPace) { land() }
        DispatchQueue.main.asyncAfter(deadline:.now() + (duration + 0.25) * flightPace) { [weak self] in panel.orderOut(nil); if self?.flight === panel { self?.flight = nil } }
    }
    func makeWeb(_ panel:NSPanel, surface:String) -> WKWebView {
        let config = WKWebViewConfiguration(); config.userContentController.add(self,name:"agents")
        let web = WKWebView(frame:NSRect(origin:.zero,size:panel.frame.size),configuration:config)
        web.setValue(false,forKey:"drawsBackground"); web.autoresizingMask = [.width,.height]
        let bg: NSView
        if surface == "shelf" {   // chips float on their own glass; the tint only backs the native first label until the page paints
            let pointer = PointerView(frame:web.frame); pointer.onPointer = { [weak self] p in self?.pointerNext = p; self?.flushPointer() }; bg = pointer
            bg.wantsLayer = true; bg.layer?.backgroundColor = NSColor(calibratedWhite:0.13,alpha:0.9).cgColor; bg.layer?.cornerRadius = 14
        } else {
            let glass = NSVisualEffectView(frame:web.frame); glass.material = .hudWindow; glass.state = .active; glass.appearance = NSAppearance(named:.darkAqua)
            glass.wantsLayer = true; glass.layer?.cornerRadius = 13; glass.layer?.masksToBounds = true; bg = glass
        }
        bg.autoresizingMask = [.width,.height]; bg.addSubview(web)
        panel.contentView = bg; panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = surface == "view";   // chips cast their own shadows; a window shadow would box them
        panel.hidesOnDeactivate = false
        applySharing(panel); panel.collectionBehavior = [.canJoinAllSpaces,.fullScreenAuxiliary,.ignoresCycle]; panel.acceptsMouseMovedEvents = true
        loadPage(web, "agents.html")
        return web
    }
    var pointerBusy = false, pointerNext: [Double]?, pointerHand = false
    func flushPointer() {   // one evaluation in flight; later moves coalesce into the newest position
        guard !pointerBusy, let next = pointerNext, ready.contains("shelf") else { return }
        pointerNext = nil; pointerBusy = true
        shelfWeb?.evaluateJavaScript("agents.pointer(\(next))") { [weak self] hand, _ in
            guard let self else { return }
            pointerBusy = false
            if (hand as? Bool ?? false) != pointerHand { pointerHand.toggle(); (pointerHand ? NSCursor.pointingHand : NSCursor.arrow).set() }   // Rabik never activates: WebKit sets no cursor here, as for the box's ×
            flushPointer()
        }
    }
    func ensureShelf(preload:Bool = false) {
        guard shelf == nil, preload || hasLive else { return }
        let screen = mouseScreen
        let bounds = screen.visibleFrame, saved = (Prefs.d["agentFrames"] as? [String:[Double]])?[MeetingFrame.key(screen)]
        let f = Self.shelfFrame(NSRect(x:0,y:0,width:260,height:52),bounds,saved)
        let panel = ShelfPanel(contentRect:f,styleMask:[.nonactivatingPanel,.borderless],backing:.buffered,defer:false)
        panel.level = .statusBar; shelf = panel; shelfWeb = makeWeb(panel,surface:"shelf"); if !preload { panel.orderFrontRegardless() }
        let title = NSTextField(labelWithString:""), step = NSTextField(labelWithString:"Starting…")
        title.frame = NSRect(x:14,y:15,width:118,height:16); title.font = .systemFont(ofSize:11.5,weight:.semibold); title.textColor = .white; title.lineBreakMode = .byTruncatingTail
        step.frame = NSRect(x:136,y:16,width:110,height:14); step.font = .systemFont(ofSize:10.5); step.textColor = .secondaryLabelColor
        panel.contentView?.addSubview(title); panel.contentView?.addSubview(step); startingLabel = title; startingStep = step
    }
    func remember() {
        guard let shelf, let screen = shelf.screen else { return }
        let bounds = screen.visibleFrame; var f = shelf.frame
        let distances = [abs(f.minX-bounds.minX),abs(bounds.maxX-f.maxX),abs(f.minY-bounds.minY),abs(bounds.maxY-f.maxY)]
        switch distances.firstIndex(of:distances.min()!) {
        case 0: f.origin.x = bounds.minX+8
        case 1: f.origin.x = bounds.maxX-f.width-8
        case 2: f.origin.y = bounds.minY+8
        default: f.origin.y = bounds.maxY-f.height-8
        }
        shelf.setFrame(MeetingFrame.clamp(f,bounds),display:true)
        var frames = Prefs.d["agentFrames"] as? [String:[Double]] ?? [:]; frames[MeetingFrame.key(screen)] = [f.minX,f.maxY]
        Prefs.set("agentFrames",frames)
    }
    func openView(_ id:String = "") {
        start()
        if view == nil {
            let screen = mouseScreen
            let f = MeetingFrame.clamp(NSRect(x:screen.visibleFrame.midX-380,y:screen.visibleFrame.midY-290,width:760,height:580),screen.visibleFrame)
            let panel = KeyPanel(contentRect:f,styleMask:[.titled,.closable,.resizable,.nonactivatingPanel,.fullSizeContentView],backing:.buffered,defer:false)
            panel.title = "Agents"; panel.titleVisibility = .hidden; panel.titlebarAppearsTransparent = true
            panel.minSize = NSSize(width:520,height:340); panel.isReleasedWhenClosed = false
            view = panel; viewWeb = makeWeb(panel,surface:"view")
            if let bg = panel.contentView { viewWeb?.frame = NSRect(x:0,y:0,width:bg.bounds.width,height:bg.bounds.height-28) }   // the glass strip above keeps the traffic lights and window drag native
            NotificationCenter.default.addObserver(forName:NSWindow.willCloseNotification,object:panel,queue:.main) { [weak self] _ in
                self?.closeView()
            }
        }
        js("view","visible",true)
        view?.orderFrontRegardless(); view?.makeKey(); view?.makeFirstResponder(viewWeb)
        let id = id.isEmpty ? sorted.first(where:{ ["needs-you","running","waiting-screen","queued"].contains($0["status"] as? String ?? "") })?["id"] as? String ?? "" : id   // menu and pill land on the live agent
        if !id.isEmpty { selected = id; js("view","select",id); preview(id,surface:"view") }
        js("view","list",sorted)
    }
    func preview(_ id:String, surface:String, target:[String:Any]? = nil) {
        let changed = hovered != id || miniSurface != surface
        hovered = id; miniSurface = surface
        guard !id.isEmpty, let row = rows[id], let target = target ?? row["target"] as? [String:Any],
              let bg = (surface == "view" ? view : shelf)?.contentView,
              let web = surface == "view" ? viewWeb : shelfWeb else { endPreview(); return }
        if changed { mini.reset() }
        if mini.clip.superview !== bg { mini.clip.removeFromSuperview(); bg.addSubview(mini.clip,positioned:.above,relativeTo:web) }   // over the chip's glass, which would hide it; clicks pass to the page
        app.mini.timer?.invalidate(); app.mini.timer = nil; app.mini.stopCapture(clear:false)   // main preview yields while an agent is inspected
        mini.receive(target)
        if row["status"] as? String == "done" { mini.finish() }
    }
    var sharing: Bool { Prefs.bool("agentsHidden") }   // macOS has no public global capture signal; this also covers silent screen-only presentations
    var quiet: Bool { meeting.running || sharing }
    func endPreview() {
        hovered = ""; mini.reset()
        if app.busy, let target = app.mini.target { app.mini.receive(target) }
    }
    var lingering = false   // the page shows finished agents (their chips or the "✓ N done" pill)
    // Finished or last seen in the past 10 minutes, e.g. before a restart: the shelf page must exist to show it (ui/agents.html LINGER).
    static func lingers(_ r:[String:Any]) -> Bool {
        ["done","failed"].contains(r["status"] as? String ?? "") && Date().timeIntervalSince1970 - max(r["ended"] as? Double ?? 0, r["seenAt"] as? Double ?? 0) < 600
    }
    var hasChips: Bool { lingering || rows.values.contains { ["running","needs-you","waiting-screen","queued"].contains($0["status"] as? String ?? "") && !dismissed.contains($0["id"] as? String ?? "") } }
    func closeView() {
        endPreview(); js("view","visible",false)
        guard hasChips, !quiet else { return }
        shelf?.orderFrontRegardless(); js("shelf","resume")
    }
    func notify(_ row:[String:Any]) {
        let p = py(["--agent-notify", row["summary"] as? String ?? row["title"] as? String ?? "Your task is done"])
        p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice; try? p.run()
    }
    func dismissPing(_ id:String) {
        send(["action":"seen","id":id]); ping = nil; app.pinned = false; app.hide(after:1)   // answered: it folds into the shelf's "done" pill
    }
    // A main ask that showed it (--agent-show): a done one's card in the box; one still working, or failed, opens in the Agent view.
    func show(_ id:String) {
        guard let row = rows[id] else { return }
        guard row["status"] as? String == "done" else { openView(id); return }
        if let old = ping, old != id { send(["action":"seen","id":old]) }   // the card this one replaces was on screen; unseen, it would ping again after a restart
        ping = id
        app.show()
        app.pinned = true; app.agentCard = id; app.js("agentDone",row)   // seen once the user acts on it (dismissPing, open, or an ask/close over it in tick)
    }
    // A finish shows on its own chip, opened with its result; the box stays as the user left it. Seen once the user opens or hides it.
    func expand(_ id:String) {
        dismissed.remove(id); ensureShelf(preload:true)
        if ready.contains("shelf") { js("shelf","expand",id) } else { expandOnReady = id }
        app.sound("Hero", min(1, Float(Prefs.num("volume")) * 2))   // its own, louder chime: the user is usually busy elsewhere when an agent finishes
    }
    // Near the shelf but not on it for 0.3 s: it fades and lets clicks through. Every mouse move checks it, so it is back as the pointer arrives.
    func fade() {
        guard let shelf, shelf.isVisible else { return }
        let point = NSEvent.mouseLocation, inside = shelf.frame.contains(point), near = shelf.frame.insetBy(dx:-60,dy:-30).contains(point)
        if inside || !near { nearSince = nil } else if nearSince == nil { nearSince = Date() }
        let fade = nearSince.map { Date().timeIntervalSince($0) >= 0.3 } ?? false
        guard shelf.ignoresMouseEvents != fade else { return }
        shelf.ignoresMouseEvents = fade; NSAnimationContext.runAnimationGroup { $0.duration = fade ? 0.2 : 0.08; shelf.animator().alphaValue = fade ? 0.25 : 1 }   // eased, never a snap; back fast: the pointer slows near a chip it aims at, so arrival often finds it faded
        if inside { (shelf.contentView as? PointerView)?.here() }   // AppKit sends no mouseEntered to a window that stops ignoring the mouse under it
    }
    func tick() {
        guard !rows.isEmpty else { shelf?.orderOut(nil); return }
        let box: [String:Any] = ["action":"box","busy":app.busy,"typing":app.composing,"listening":app.engine.isRunning,"quiet":quiet]
        if lastBox?.isEqual(to:box) != true { lastBox = NSDictionary(dictionary:box); send(box) }
        if let shelf {
            let hidden = quiet   // never hide in full screen: he works in full-screen apps on both displays
            if hidden || !hasChips {
                if shelf.isVisible { shelf.orderOut(nil); js("shelf","visible",false); pointerNext = []; flushPointer() }   // once, not every tick; a hidden panel gets no mouseExited, so its hover, .near and hand cursor end here
                moves.forEach(NSEvent.removeMonitor); moves = []
                if miniSurface == "shelf", mini.target != nil { endPreview() }
            }
            else {
                if !shelf.isVisible { shelf.orderFrontRegardless(); js("shelf","visible",true) }
                if moves.isEmpty {   // only while the shelf is up: a global move monitor wakes the app on every mouse move anywhere
                    moves = [NSEvent.addGlobalMonitorForEvents(matching:.mouseMoved) { [weak self] _ in self?.fade() },   // a faded shelf gets no mouse events: other apps' moves bring it back
                             NSEvent.addLocalMonitorForEvents(matching:.mouseMoved) { [weak self] e in self?.fade(); return e },
                             NSEvent.addGlobalMonitorForEvents(matching:.leftMouseDown) { [weak self] _ in self?.js("shelf","blur") }].compactMap { $0 }   // a click in another app
                }
                fade()
            }
            follow()
        }
        if let id = ping, !app.panel.isVisible || app.busy || app.engine.isRunning {   // the user closed the box or asked over the card
            send(["action":"seen","id":id]); ping = nil; app.agentCard = ""; app.pinned = false; app.defaultKey(false); app.js("agentCancelled")
        }
    }
    func open(_ id:String, target:String? = nil, reveal:Bool = false) {
        guard let row = rows[id] else { return }
        app.allowUntil = Date().addingTimeInterval(3); app.allowUserApp = true   // a click in our own panel never reaches the global monitor, so the focus guard took this for an app raising itself
        if row["destination"] as? String == "meeting" { meeting.open(); meeting.showAgentPrep(row); return }
        let raw = target ?? ((row["made"] as? [[String:Any]])?.first?["url"] as? String) ?? (row["links"] as? [String])?.first   // the main thing it made
        if let raw {
            if let url = URL(string:raw), ["https","http"].contains(url.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(url); return }
            let path = raw.hasPrefix("file://") ? URL(string:raw)?.path ?? "" : NSString(string:raw).expandingTildeInPath
            let root = row["directory"] as? String ?? ""
            let url = URL(fileURLWithPath:path.hasPrefix("/") ? path : root + "/" + path).standardizedFileURL
            if FileManager.default.fileExists(atPath:url.path) {
                if reveal { NSWorkspace.shared.activateFileViewerSelecting([url]) } else { NSWorkspace.shared.open(url) }; return
            }
        }
        if reveal, let folder = row["directory"] as? String { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath:folder)]); return }
        if let target = row["target"] as? [String:Any] { mini.receive(target); mini.open(); mini.reset() }
        else { openView(id) }
    }
    func userContentController(_ controller:WKUserContentController,didReceive message:WKScriptMessage) {
        guard let body = message.body as? [String:Any], let action = body["action"] as? String else { return }
        let surface = message.webView === viewWeb ? "view" : "shelf", id = body["id"] as? String ?? ""
        switch action {
        case "ready":
            ready.insert(surface); js(surface,"mode",surface); js(surface,"prefs",["dismissed":Array(dismissed),"stack":Prefs.str("agentStack")]); js(surface,"list",sorted); if surface == "view" { js(surface,"named",named); if !selected.isEmpty { js(surface,"select",selected) } }
            if surface == "shelf" {
                js(surface,"visible",shelf?.isVisible == true)   // a preloaded shelf starts hidden; tick only reports changes
                if !expandOnReady.isEmpty { js(surface,"expand",expandOnReady); expandOnReady = "" }
                shelfWeb?.evaluateJavaScript("document.querySelector('.chip') !== null") { [weak self] _, _ in
                    self?.startingLabel?.removeFromSuperview(); self?.startingStep?.removeFromSuperview(); self?.startingLabel = nil; self?.startingStep = nil
                    self?.shelf?.contentView?.layer?.backgroundColor = nil
                }
            }
        case "size":
            guard surface == "shelf", let shelf, let h = body["h"] as? Double, h.isFinite, let screen = shelf.screen else { return }
            var f = shelf.frame; f.origin.y = f.maxY - max(52,h); f.size.height = max(52,h)
            let next = MeetingFrame.clamp(f,screen.visibleFrame); if next != shelf.frame { shelf.setFrame(next,display:false) }   // once per state change; the page already laid out
        case "drag": if let shelf { drag = (NSEvent.mouseLocation,shelf.frame) }
        case "dismiss":
            if rows[id]?["status"] as? String == "done" { send(["action":"seen","id":id]); rows[id]?["seenAt"] = Date().timeIntervalSince1970 }   // as rabik.py saves it, so the saved list keeps it
            dismissed.insert(id)
            if hovered == id, miniSurface == "shelf" { endPreview() }
        case "stack": Prefs.set("agentStack",body["value"] as? String ?? "")
        case "view", "show": openView(id); if rows[id]?["status"] as? String == "done" { send(["action":"seen","id":id]) }   // a finished chip clicked open
        case "lingering": lingering = body["value"] as? Bool ?? false; tick()
        case "close": if surface == "view" { view?.orderOut(nil); closeView() }
        case "hover":
            if id.isEmpty { endPreview() }
            else if hovered != id || miniSurface != surface { preview(id,surface:surface) }
        case "miniRect":
            guard miniSurface == surface, let web = surface == "view" ? viewWeb : shelfWeb, let bg = web.superview else { return }
            var value = body; let off = bg.bounds.height - web.frame.maxY   // the Agent view's page starts below its title strip
            for key in ["rect","clip"] { if var r = value[key] as? [Double], r.count == 4 { r[1] += off; value[key] = r } }
            mini.layout(value)
        case "attention": if !quiet { shelf?.orderFrontRegardless() }
        case "open": open(id,target:body["target"] as? String); if rows[id]?["status"] as? String == "done" { send(["action":"seen","id":id]) }
        case "reveal": open(id,reveal:true)
        case "connect": NSWorkspace.shared.open(URL(string:"https://claude.ai/settings/connectors")!)
        case "answer":
            send(body)
            if body["answer"] as? String == "y", let q = rows[id]?["question"] as? [String:Any], q["need"] != nil, q["_a"] as? String == body["question"] as? String { allow(id,q) }
        default: send(body)
        }
    }
}
