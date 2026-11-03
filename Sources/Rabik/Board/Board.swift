// The live board. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa
import WebKit

// A reply that starts with [board …] (brain/board.py) arrives as "◫ {event}" lines while it streams. This card, a little right
// of the screen's middle, draws it (ui/board.html): each `say` line is spoken through Rabik's Speaker, and when that sentence
// starts playing the page draws the marks that followed it across the sentence's length. With voice off it keeps reading pace.
// Follow-ups see what is on it (summary); clicking a 3D part asks about that part; ⤓ saves it to Downloads as a PNG.
final class Board: NSObject, WKScriptMessageHandler {
    private(set) var panel: NSPanel?
    private var web: WKWebView?
    private var ready = false, waiting: [(String, [Any])] = [], summaryWanted = false
    private var generation = 0, segment = 0, paceUntil = Date.distantPast, quiet = false   // quiet: the voice was stopped, the rest goes at reading pace
    private(set) var summary: [String: Any]?
    var speak: ((String, @escaping (Double) -> Void) -> Bool)?   // App: speak one line, call back when it starts (seconds long); false: not speaking
    var onAsk: ((String) -> Void)?
    var visible: Bool { panel?.isVisible == true }

    func receive(_ line: String) {
        guard let data = line.data(using: .utf8), let event = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let op = event["op"] as? String else { return }
        switch op {
        case "open":
            var event = event
            if event["append"] as? Bool != true || !visible { summary = nil; event["append"] = false }   // [board+] adds only to a board still on screen
            generation += 1; segment = 0; paceUntil = .distantPast; quiet = false   // an earlier answer's paced lines never play into this one
            show(); js("board.open", [event])
        case "say":
            guard visible else { return }   // closed with ✕: the rest of this answer neither draws nor speaks
            segment += 1
            let n = segment, g = generation, text = event["text"] as? String ?? ""
            js("board.add", [event])
            let start = { [weak self] (seconds: Double) in guard let self, g == generation else { return }; js("board.play", [n, seconds]) }
            if quiet || speak?(text, start) != true {   // voice off or stopped: one line after another at reading pace
                let seconds = Speaker.readingTime(text), at = max(Date(), paceUntil)
                paceUntil = at.addingTimeInterval(seconds)
                DispatchQueue.main.asyncAfter(deadline: .now() + at.timeIntervalSinceNow) { start(seconds) }
            }
        case "end":
            js("board.end", []); refreshSummary()
        case "drop":
            close()
        default:
            guard visible else { return }
            js("board.add", [event])
        }
    }

    // Speech stopped (the user talked or pressed the shortcut): draw what is left now.
    func flush() { if visible { quiet = true; js("board.flush", []) } }

    func close() {
        generation += 1; summary = nil
        panel?.orderOut(nil)
    }

    private func refreshSummary() {
        guard ready else { summaryWanted = true; return }   // the page is still loading: asked again once it is ready
        let g = generation
        web?.evaluateJavaScript("board.summary()") { [weak self] value, _ in
            guard let self, g == generation else { return }; summary = value as? [String: Any]
        }
    }

    private func show() {
        if panel == nil { make() }
        guard let panel else { return }
        if !panel.isVisible { panel.setFrame(Board.frame(in: mouseScreen.visibleFrame), display: false) }
        panel.orderFrontRegardless()
    }

    // In the middle of the screen, a little to the right of it, so the box and the app on the left stay in sight.
    static func frame(in vf: NSRect) -> NSRect {
        let w = min(780, vf.width * 0.6), h = min(520, vf.height * 0.66)
        let x = min(vf.maxX - w - 16, max(vf.minX + 16, vf.midX - w / 2 + vf.width * 0.12))
        return NSRect(x: x.rounded(), y: (vf.midY - h / 2).rounded(), width: w.rounded(.down), height: h.rounded(.down))
    }

    private func make() {
        let p = BoardPanel(contentRect: Board.frame(in: mouseScreen.visibleFrame), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.level = .floating; p.isOpaque = false; p.backgroundColor = .clear; p.hasShadow = true; p.hidesOnDeactivate = false
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]; applySharing(p)
        let cfg = WKWebViewConfiguration(); cfg.userContentController.add(self, name: "board")
        let v = WKWebView(frame: NSRect(origin: .zero, size: p.frame.size), configuration: cfg)
        v.setValue(false, forKey: "drawsBackground"); v.autoresizingMask = [.width, .height]
        let root = NSView(frame: v.frame); root.wantsLayer = true; root.layer?.cornerRadius = 18; root.layer?.masksToBounds = true
        root.addSubview(v)
        let strip = DragStrip(frame: NSRect(x: 0, y: v.frame.height - 46, width: v.frame.width - 84, height: 46))   // the title bar, left of ⤓ and ✕
        strip.autoresizingMask = [.width, .minYMargin]; root.addSubview(strip)
        p.contentView = root; panel = p; web = v; ready = false
        loadPage(v, "board.html")
    }

    private func js(_ fn: String, _ args: [Any]) {
        guard ready else { waiting.append((fn, args)); return }
        callJS(web, fn, args)
    }

    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard m.frameInfo.isMainFrame, m.webView === web, let b = m.body as? [String: Any], let action = b["do"] as? String else { return }
        switch action {
        case "ready":
            ready = true; let calls = waiting; waiting = []; calls.forEach { callJS(web, $0.0, $0.1) }
            if summaryWanted { summaryWanted = false; refreshSummary() }
        case "close": close()
        case "save": save(b["title"] as? String ?? "")
        case "ask":
            guard let part = b["part"] as? String, !part.isEmpty else { return }
            let title = b["title"] as? String ?? ""
            let turkish = (title + part).range(of: "[çğıöşüÇĞİÖŞÜ]", options: .regularExpression) != nil
            onAsk?(turkish ? "\(part) ne işe yarar?" + (title.isEmpty ? "" : " (\(title))") : "What does the \(part) do?" + (title.isEmpty ? "" : " (\(title))"))
        default: break
        }
    }

    // ⤓: the card as a picture in Downloads ("Rabik board – <title>.png"), then a short "Saved" on the card.
    private func save(_ title: String) {
        web?.takeSnapshot(with: nil) { [weak self] image, _ in
            guard let self, let image, let tiff = image.tiffRepresentation, let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) else { return }
            let name = title.replacingOccurrences(of: "/", with: "-").trimmingCharacters(in: .whitespaces)
            let stamp = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH.mm.ss"; return f.string(from: Date()) }()
            let folder = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first ?? URL(fileURLWithPath: NSHomeDirectory())
            let url = folder.appendingPathComponent("Rabik board – \(name.isEmpty ? "board" : name) \(stamp).png")
            if (try? png.write(to: url)) != nil { js("board.saved", []) }
        }
    }
}

// Never key: the card shows and takes clicks without pulling Rabik forward or taking typing from the user's app.
final class BoardPanel: NSPanel { override var canBecomeKey: Bool { false } }

// The board's title bar, over the page: dragging it moves the card.
final class DragStrip: NSView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func mouseDown(with e: NSEvent) { window?.performDrag(with: e) }
}
