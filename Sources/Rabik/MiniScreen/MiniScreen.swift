// The mini screen: a live, window-only view of the app an ask works in. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// Mini screen: local window-only buffers stay in a native layer, underneath the transparent web controls.
final class PassView: NSView { override func hitTest(_ point: NSPoint) -> NSView? { nil } }   // shows, never takes the click

final class MiniScreen: NSObject, SCStreamOutput, SCStreamDelegate {
    static var captureStop: Task<Void,Never>?   // a new preview waits until the previous stream has actually stopped
    let clip = PassView(), picture = AVSampleBufferDisplayLayer(), previous = AVSampleBufferDisplayLayer()
    var lastSample: CMSampleBuffer?, transitioning = false
    var stream: SCStream?, target: [String:Any]?, timer: Timer?, ending: DispatchWorkItem?
    var forcePreview = false, captureAllowed: (() -> Bool)?
    var publish: (([String:Any]) -> Void)?
    var retry = Date.distantPast
    var generation = 0, shown = false, live = false, starting = false, failed = false, frames = 0
    override init() {
        super.init()
        clip.wantsLayer = true; clip.layer?.masksToBounds = true; clip.isHidden = true
        picture.videoGravity = .resizeAspect; picture.cornerRadius = 12; picture.masksToBounds = true
        picture.backgroundColor = NSColor.black.cgColor; clip.layer?.addSublayer(picture)
        previous.videoGravity = .resizeAspect; previous.cornerRadius = 12; previous.masksToBounds = true
        previous.backgroundColor = NSColor.black.cgColor; previous.opacity = 0; clip.layer?.addSublayer(previous)
    }
    static func activate(_ pid: Int32) {
        // System Events addresses the running process; cooperative AppKit activation can be refused from our background panel.
        _ = NSRunningApplication(processIdentifier: pid)?.activate()
        let p = Process(); p.executableURL = URL(fileURLWithPath:"/usr/bin/osascript")
        p.arguments = ["-e", "tell application \"System Events\" to set frontmost of (first application process whose unix id is \(pid)) to true"]
        p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
        let timeout = DispatchWorkItem { if p.isRunning { p.terminate() } }
        p.terminationHandler = { process in process.terminationHandler = nil; timeout.cancel() }
        guard (try? p.run()) != nil else { p.terminationHandler = nil; return }
        DispatchQueue.global().asyncAfter(deadline: .now() + 2, execute: timeout)
    }
    static var workInFront: Bool { Prefs.str("workIn") == "front" || ProcessInfo.processInfo.environment["RABIK_FOCUS_REQUESTED"] == "1" }
    static func work(_ app: NSRunningApplication) {
        guard workInFront, NSWorkspace.shared.frontmostApplication != app else { return }
        DistributedNotificationCenter.default().postNotificationName(.init("rabik.raise"), object: "user", deliverImmediately: true)
        usleep(50_000); activate(app.processIdentifier)
    }
    static func bounds(_ info: [String:Any]) -> CGRect? {
        (info[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation:$0) }
    }
    // Visible = on displays and at most 10% under normal windows in front of it: input reaches it without raising it.
    static func visible(_ r: CGRect, displays: [CGRect], above: [CGRect]) -> Bool {
        let area = { (a: CGRect) in a.isNull ? 0 : a.width * a.height }
        return area(r) > 0 && displays.reduce(0) { $0 + area($1.intersection(r)) } >= area(r) * 0.9 && above.reduce(0) { $0 + area($1.intersection(r)) } <= area(r) * 0.1
    }
    // Where a window (top-left points) lands in its display's 1280-wide --look picture, in CoreGraphics' bottom-up drawing space.
    static func paintRect(_ w: CGRect, display d: CGRect, pictureHeight: Int) -> CGRect {
        let s = 1280 / d.width
        return CGRect(x: (w.minX - d.minX) * s, y: CGFloat(pictureHeight) - (w.maxY - d.minY) * s, width: w.width * s, height: w.height * s)
    }
    static func windowTarget(_ app: NSRunningApplication, title: String = "", frame: [Double] = [], screen: CGRect? = nil, windows: [[String:Any]]) -> [String:Any]? {
        if !frame.isEmpty && (frame.count != 4 || !frame.allSatisfy(\.isFinite)) { return nil }
        let root = AXUIElementCreateApplication(app.processIdentifier)
        let elements = axAttribute(root, kAXWindowsAttribute) as? [AXUIElement] ?? []
        let preferred = axAttribute(root,kAXFocusedWindowAttribute).flatMap { CFGetTypeID($0) == AXUIElementGetTypeID() ? axWindowNumber($0 as! AXUIElement) : nil }
        let named = windows.map { info -> [String:Any] in
            var value = info
            if (info[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == app.processIdentifier,
               info[kCGWindowName as String] == nil, let number = info[kCGWindowNumber as String] as? NSNumber,
               let w = elements.first(where: { axWindowNumber($0) == number }) {
                value[kCGWindowName as String] = axAttribute(w,kAXTitleAttribute) as? String
            }
            return value
        }
        let candidates = named.filter {
            ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == app.processIdentifier &&
            ($0[kCGWindowLayer as String] as? Int) == 0 && bounds($0).map { $0.width > 1 && $0.height > 1 && ($0.height > 40 || $0.width < $0.height * 10) } == true &&
            (title.isEmpty || ($0[kCGWindowName as String] as? String ?? "").localizedCaseInsensitiveContains(title)) &&
            (frame.isEmpty || bounds($0).map { abs($0.minX-frame[0]) < 2 && abs($0.minY-frame[1]) < 2 && abs($0.width-frame[2]) < 2 && abs($0.height-frame[3]) < 2 } == true) &&
            (screen == nil || bounds($0).map { screen!.contains(CGPoint(x:$0.midX,y:$0.midY)) } == true)
        }
        if !frame.isEmpty && candidates.count != 1 { return nil }   // indistinguishable windows are not a safe preview target
        let real = Set(elements.compactMap(axWindowNumber))   // apps own invisible full-width strips; AX lists only real windows
        let area = { (w: [String:Any]) in bounds(w).map { $0.width * $0.height } ?? 0 }
        guard let w = candidates.first(where: { ($0[kCGWindowNumber as String] as? NSNumber) == preferred })
                ?? candidates.first(where: { ($0[kCGWindowNumber as String] as? NSNumber).map(real.contains) == true })
                ?? candidates.max(by: { area($0) < area($1) }),   // no AX (other Space): the strips are always the smallest
              let frame = bounds(w), let number = w[kCGWindowNumber as String] as? NSNumber else { return nil }
        let minimized = elements.contains { axWindowNumber($0) == number && axAttribute($0,kAXMinimizedAttribute) as? Bool == true }
        return ["pid":app.processIdentifier,"windowID":number.stringValue,"windowFrame":[frame.minX,frame.minY,frame.width,frame.height],
                "window":w[kCGWindowName as String] as? String ?? app.localizedName ?? "Window","app":app.localizedName ?? "App","minimized":minimized]
    }
    var pid: Int32 { (target?["pid"] as? NSNumber)?.int32Value ?? 0 }
    var id: UInt32 { UInt32(target?["windowID"] as? String ?? "") ?? 0 }
    var holds: Bool { target != nil && shown && timer == nil }
    func receive(_ value: [String:Any]) {
        guard let p = value["pid"] as? NSNumber, p.int32Value > 0,
              let w = value["windowID"] as? String, UInt32(w).map({ $0 > 0 }) == true,
              let f = value["windowFrame"] as? [Double], f.count == 4, f.allSatisfy(\.isFinite), f[2] > 0, f[3] > 0 else { return }
        ending?.cancel(); ending = nil
        failed = false
        let icon = pid == p.int32Value ? target?["icon"] as? String : nil
        let changed = pid != p.int32Value || id != UInt32(w)!
        if changed {
            let old = lastSample; stopCapture(clear:false); failed = false; frames = 0
            if let old { previous.sampleBufferRenderer.enqueue(old); previous.opacity = 1; transitioning = true }
        }
        target = value
        if let icon { target?["icon"] = icon }
        else if let app = NSRunningApplication(processIdentifier:p.int32Value), let icon = app.icon,
           let data = icon.tiffRepresentation, let bitmap = NSBitmapImageRep(data:data), let png = bitmap.representation(using:.png,properties:[:]) {
            target?["icon"] = "data:image/png;base64," + png.base64EncodedString()
        }
        if timer == nil { timer = Timer.scheduledTimer(withTimeInterval:0.5,repeats:true) { [weak self] _ in self?.refresh() } }
        refresh(force:true)
    }
    // Preview a window the user can't see: not on screen (other Space, minimized, hidden, behind full screen), or over a quarter
    // of it off every awake display or under other windows. The quarter lets near-transparent overlays (dictation HUDs) and an
    // app's own toolbar strips sit on top without counting as cover; CGWindow info can't tell a transparent window apart.
    static func needsPreview(pid: Int32, id: UInt32, windows: [[String:Any]], displays: [CGRect]) -> Bool {
        guard let index = windows.firstIndex(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == id && ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid }),
              let frame = bounds(windows[index]), frame.width > 0, frame.height > 0 else { return true }
        let covers = windows.prefix(index).compactMap { w -> CGRect? in
            guard (w[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value != ProcessInfo.processInfo.processIdentifier,
                  (w[kCGWindowAlpha as String] as? Double ?? 1) > 0, let b = bounds(w), b.width > 1, b.height > 1 else { return nil }
            return b
        }
        let n = 20, hidden = (0..<n*n).filter { k in
            let p = CGPoint(x:frame.minX + frame.width * (Double(k % n) + 0.5) / Double(n), y:frame.minY + frame.height * (Double(k / n) + 0.5) / Double(n))
            return !displays.contains { $0.contains(p) } || covers.contains { $0.contains(p) }
        }.count
        return hidden * 4 > n * n
    }
    func refresh(force: Bool = false) {
        guard target != nil, ending == nil else { return }
        let oldFrame = target?["windowFrame"] as? [Double]
        let oldMinimized = target?["minimized"] as? Bool ?? false
        let elements = axAttribute(AXUIElementCreateApplication(pid), kAXWindowsAttribute) as? [AXUIElement] ?? []
        if let w = elements.first(where: { axWindowNumber($0)?.uint32Value == id }) { target?["minimized"] = axAttribute(w,kAXMinimizedAttribute) as? Bool ?? false }
        let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] ?? []
        if let window = windows.first(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == id && ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid }), let f = Self.bounds(window), f.width > 0, f.height > 0 {
            target?["windowFrame"] = [f.minX,f.minY,f.width,f.height].map(Double.init)
            if let oldFrame, oldFrame[2] != f.width || oldFrame[3] != f.height, let s = stream { Task { try? await s.updateConfiguration(Self.configuration(f)) } }
        }
        var ids = [CGDirectDisplayID](repeating:0,count:16), count: UInt32 = 0
        CGGetActiveDisplayList(16,&ids,&count)
        let displays = ids.prefix(Int(count)).filter { CGDisplayIsAsleep($0) == 0 }.map(CGDisplayBounds)
        let next = forcePreview || Self.needsPreview(pid:pid,id:id,windows:windows,displays:displays)
        let changed = shown != next; shown = next
        if failed && Date() >= retry { failed = false }
        if !shown || captureAllowed?() == false { stopCapture(clear:false) }
        else if target?["minimized"] as? Bool == true { stopCapture(clear:true) }
        else if stream == nil && !starting && !failed && CGPreflightScreenCaptureAccess() { startCapture() }
        if force || changed || oldFrame != target?["windowFrame"] as? [Double] || oldMinimized != (target?["minimized"] as? Bool ?? false) { send() }
    }
    func send() {
        guard var value = target else { return }; value["shown"] = shown; value["live"] = live || transitioning; publish?(value)
    }
    static func configuration(_ frame: CGRect) -> SCStreamConfiguration {
        let cfg = SCStreamConfiguration(), scale = min(600 / max(1,frame.width),375 / max(1,frame.height))
        cfg.width = max(1,Int((frame.width * scale).rounded())); cfg.height = max(1,Int((frame.height * scale).rounded()))
        cfg.minimumFrameInterval = CMTime(value:1,timescale:12); cfg.showsCursor = false
        cfg.ignoreShadowsSingleWindow = true; cfg.queueDepth = 3; cfg.scalesToFit = true; cfg.preservesAspectRatio = true
        return cfg   // matching the window aspect leaves letterboxing to the centered native layer
    }
    func startCapture() {
        generation += 1; let token = generation, windowID = id, processID = pid
        starting = true
        Task { @MainActor [weak self] in
            await Self.captureStop?.value
            let all = try? await SCShareableContent.excludingDesktopWindows(true,onScreenWindowsOnly:false)
            guard let self, generation == token, shown else { return }
            guard let w = all?.windows.first(where: { $0.windowID == windowID && $0.owningApplication?.processID == processID }) else { starting = false; failed = true; retry = Date().addingTimeInterval(3); stopCapture(clear:false); send(); return }
            let cfg = Self.configuration(w.frame)
            let s = SCStream(filter:SCContentFilter(desktopIndependentWindow:w),configuration:cfg,delegate:self)
            do {
                try s.addStreamOutput(self,type:.screen,sampleHandlerQueue:.main); stream = s
                try await s.startCapture()
                if generation != token { try? await s.stopCapture() }
            } catch { if generation == token { failed = true; retry = Date().addingTimeInterval(3); stopCapture(clear:false); send() } }
        }
    }
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard self.stream === stream, type == .screen, sample.isValid,
              let attachments = CMSampleBufferGetSampleAttachmentsArray(sample,createIfNecessary:false) as? [[SCStreamFrameInfo:Any]],
              let status = attachments.first?[.status] as? Int, status == SCFrameStatus.complete.rawValue else { return }
        if picture.sampleBufferRenderer.status == .failed { picture.sampleBufferRenderer.flush(removingDisplayedImage:false) }
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample,createIfNecessary:true) as? [NSMutableDictionary], let info = attachments.first { info[kCMSampleAttachmentKey_DisplayImmediately] = true }
        picture.sampleBufferRenderer.enqueue(sample); lastSample = sample; frames += 1
        if transitioning {
            transitioning = false
            let fade = CABasicAnimation(keyPath:"opacity"); fade.fromValue = 1; fade.toValue = 0; fade.duration = 0.24
            previous.opacity = 0; previous.add(fade,forKey:"switch")
            let token = generation
            DispatchQueue.main.asyncAfter(deadline:.now() + 0.25) { [weak self] in if self?.generation == token { self?.previous.sampleBufferRenderer.flush(removingDisplayedImage:true) } }
        }
        if !live { live = true; starting = false; send() }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.stream === stream else { return }; failed = true; retry = Date().addingTimeInterval(3); stopCapture(clear:false); send()
        }
    }
    func stopCapture(clear: Bool) {
        generation += 1; starting = false
        if let s = stream {
            stream = nil; let previous = Self.captureStop
            Self.captureStop = Task { await previous?.value; try? await s.stopCapture() }
        }
        if clear { live = false; transitioning = false; lastSample = nil; picture.sampleBufferRenderer.flush(removingDisplayedImage:true); previous.removeAllAnimations(); previous.opacity = 0; previous.sampleBufferRenderer.flush(removingDisplayedImage:true); clip.isHidden = true }
    }
    func finish() {
        guard target != nil, ending == nil else { return }
        timer?.invalidate(); timer = nil; stopCapture(clear:false)   // freeze the last buffer; it stays until the next ask, typing, or a click on it (the page clears it)
    }
    func reset() {
        ending?.cancel(); ending = nil; timer?.invalidate(); timer = nil
        stopCapture(clear:true); target = nil; shown = false; failed = false
    }
    func layout(_ value: [String:Any]) {
        guard let r = value["rect"] as? [Double], r.count == 4, r.allSatisfy(\.isFinite),
              let c = value["clip"] as? [Double], c.count == 4, c.allSatisfy(\.isFinite), let height = clip.superview?.bounds.height else { clip.isHidden = true; return }
        CATransaction.begin(); CATransaction.setDisableActions(true)
        clip.frame = NSRect(x:c[0],y:height - c[1] - c[3],width:max(0,c[2]),height:max(0,c[3]))
        picture.frame = CGRect(x:r[0] - c[0],y:c[3] - (r[1] - c[1]) - r[3],width:max(0,r[2]),height:max(0,r[3]))
        picture.cornerRadius = min(12,max(0,r[3]) / 4); picture.videoGravity = value["fill"] as? Bool == true ? .resizeAspectFill : .resizeAspect   // a chip thumbnail fills its little tile
        previous.frame = picture.frame; previous.cornerRadius = picture.cornerRadius; previous.videoGravity = picture.videoGravity
        clip.layer?.opacity = Float(value["opacity"] as? Double ?? 1)
        clip.isHidden = !(live || transitioning) || r[2] <= 0 || r[3] <= 0
        CATransaction.commit()
    }
    func open() {
        guard (CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? []).contains(where: {
            ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == id && ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid
        }) else { return }
        guard let a = NSRunningApplication(processIdentifier:pid), !a.isTerminated, let f = target?["windowFrame"] as? [Double], f.count == 4 else { return }
        let processID = pid, windowID = id
        let raise = {
            let windows = axAttribute(AXUIElementCreateApplication(processID),kAXWindowsAttribute) as? [AXUIElement] ?? []
            let direct = windows.filter { axWindowNumber($0)?.uint32Value == windowID }
            let matches = direct.isEmpty ? windows.filter {
                guard let p = axAttribute($0,kAXPositionAttribute), let s = axAttribute($0,kAXSizeAttribute), CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return false }
                var origin = CGPoint.zero, size = CGSize.zero
                guard AXValueGetValue(p as! AXValue,.cgPoint,&origin), AXValueGetValue(s as! AXValue,.cgSize,&size) else { return false }
                return abs(origin.x - f[0]) < 2 && abs(origin.y - f[1]) < 2 && abs(size.width - f[2]) < 2 && abs(size.height - f[3]) < 2
            } : direct
            if matches.count == 1 {
                AXUIElementSetAttributeValue(matches[0],kAXMinimizedAttribute as CFString,kCFBooleanFalse)
                AXUIElementPerformAction(matches[0],kAXRaiseAction as CFString)
            }
        }
        Self.activate(processID); raise()
        DispatchQueue.main.asyncAfter(deadline:.now()+0.3) {   // AX windows on another Space can appear after activation returns
            if NSWorkspace.shared.frontmostApplication?.processIdentifier == processID { raise() }
        }
    }
}
