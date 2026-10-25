// Drawings and guides on screen (--draw). Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// Sees the mouse over the box without taking clicks or focus (clicks go to the monitors in App).
final class Tracker: NSView {
    var onMove: ((NSPoint) -> Void)?, onExit: (() -> Void)?
    override func hitTest(_ p: NSPoint) -> NSView? { nil }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.activeAlways, .mouseMoved, .mouseEnteredAndExited, .inVisibleRect],
                                       owner: self))
    }
    override func mouseMoved(with e: NSEvent) { onMove?(convert(e.locationInWindow, from: nil)) }
    override func mouseEntered(with e: NSEvent) { onMove?(convert(e.locationInWindow, from: nil)) }
    override func mouseExited(with e: NSEvent) { onExit?() }
}

// Screen drawings use Quartz points throughout; each flipped view translates its own display origin.
final class DrawingPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

struct DrawingShape: Codable {
    let kind: String
    var rect: [Double]?, at: [Double]?, points: [[Double]]?, text: String?, color: String?, size: String?, fill: Bool?
}

struct DrawingStep: Codable {
    let id: String?, say: String?, target: String?, shapes: [DrawingShape]
    let wait: Bool?, hit: [Double]?, timeout: Double?
}

struct DrawingRequest: Decodable {
    let steps: [DrawingStep], teaching: Bool, target: DrawingWindow, state: String
    let receipt: String?
}

struct DrawingWindow: Decodable {
    let pid: Int32, windowID: String, windowFrame: [Double]
    var bounds: CGRect { CGRect(x:windowFrame[0], y:windowFrame[1], width:windowFrame[2], height:windowFrame[3]) }
    var valid: Bool { pid > 0 && UInt32(windowID).map { $0 > 0 } == true && ScreenDrawing.validRect(windowFrame) }
}

final class DrawingView: NSView {
    override var isFlipped: Bool { true }
    var origin = CGPoint.zero
    var inputStart: ((CGPoint) -> Void)?, inputMove: ((CGPoint) -> Void)?, inputEnd: ((CGPoint) -> Void)?, inputHover: ((CGPoint?) -> Void)?
    var pick: ((CGPoint) -> Void)?
    var hits: [(area: CGPath, step: Int, shape: Int)] = []   // local points: what a click on each mark selects
    func reset() { layer?.sublayers?.forEach { $0.removeFromSuperlayer() }; hits = [] }
    func mark(at p: CGPoint) -> (bounds: CGRect, step: Int, shape: Int)? {
        let l = CGPoint(x:p.x-origin.x, y:p.y-origin.y)
        return hits.last { $0.area.contains(l) }.map { ($0.area.boundingBoxOfPath.offsetBy(dx:origin.x,dy:origin.y), $0.step, $0.shape) }
    }
    var hitBounds: [CGRect] { hits.map { $0.area.boundingBoxOfPath.offsetBy(dx:origin.x,dy:origin.y) } }
    func highlight(_ selected: (step: Int, shape: Int)?) {   // the selected mark: an accent ring, like a selection anywhere on the Mac
        layer?.sublayers?.filter { $0.name == "pick" }.forEach { $0.removeFromSuperlayer() }
        guard let selected else { return }
        for h in hits where h.step == selected.step && h.shape == selected.shape {
            let ring = CAShapeLayer(); ring.name = "pick"
            ring.path = CGPath(roundedRect:h.area.boundingBoxOfPath.insetBy(dx:-5,dy:-5),cornerWidth:8,cornerHeight:8,transform:nil)
            ring.fillColor = NSColor.controlAccentColor.withAlphaComponent(0.16).cgColor; ring.strokeColor = NSColor.controlAccentColor.cgColor; ring.lineWidth = 2
            layer?.addSublayer(ring)
        }
    }
    // A whiteboard of large text lines on one dark panel; earlier steps' lines stay, a little quieter.
    func renderBoard(_ frame: CGRect, _ lines: [ScreenDrawing.BoardLine], current: Int, animate: Bool) {
        wantsLayer = true
        guard bounds.offsetBy(dx:origin.x,dy:origin.y).intersects(frame) else { return }
        let local = frame.offsetBy(dx:-origin.x,dy:-origin.y), bg = CAShapeLayer()
        bg.path = CGPath(roundedRect:local,cornerWidth:14,cornerHeight:14,transform:nil); bg.fillColor = NSColor(calibratedWhite:0.08,alpha:0.94).cgColor
        bg.strokeColor = NSColor.white.withAlphaComponent(0.22).cgColor; bg.lineWidth = 0.5
        bg.shadowColor = NSColor.black.cgColor; bg.shadowOpacity = 0.35; bg.shadowRadius = 8; bg.shadowOffset = .zero; bg.shadowPath = bg.path
        layer?.addSublayer(bg)
        for line in lines {
            let text = CATextLayer(); text.string = line.text; text.isWrapped = true; text.contentsScale = window?.backingScaleFactor ?? 2
            text.frame = line.rect.offsetBy(dx:-origin.x,dy:-origin.y)
            if line.step < current { text.opacity = 0.7 }
            else if animate {
                let fade = CABasicAnimation(keyPath:"opacity"); fade.fromValue = 0; fade.toValue = 1; fade.duration = 0.3; text.add(fade,forKey:"write")
            }
            layer?.addSublayer(text); hits.append((CGPath(rect:text.frame.insetBy(dx:-4,dy:-2),transform:nil),line.step,line.shape))
        }
    }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    func inputPoint(_ event: NSEvent) -> CGPoint {
        let p = convert(event.locationInWindow, from:nil)
        return CGPoint(x:origin.x + p.x, y:origin.y + p.y)
    }
    var pointing: Bool { inputStart != nil && window?.ignoresMouseEvents == false }
    override func updateTrackingAreas() {
        super.updateTrackingAreas(); trackingAreas.forEach(removeTrackingArea)
        if inputStart != nil { addTrackingArea(NSTrackingArea(rect:.zero,options:[.activeAlways,.mouseMoved,.mouseEnteredAndExited,.cursorUpdate,.inVisibleRect],owner:self)) }
    }
    override func cursorUpdate(with event: NSEvent) { if pointing { NSCursor.crosshair.set() } else { super.cursorUpdate(with:event) } }   // Rabik never activates, so set it on every move too
    override func mouseEntered(with event: NSEvent) { if pointing { NSCursor.crosshair.set() } }
    override func mouseMoved(with event: NSEvent) { inputHover?(inputPoint(event)); if pointing { NSCursor.crosshair.set() } }
    override func mouseExited(with event: NSEvent) { inputHover?(nil) }
    override func mouseDown(with event: NSEvent) { if pointing { NSCursor.crosshair.set() }; inputStart?(inputPoint(event)); pick?(inputPoint(event)) }
    override func mouseDragged(with event: NSEvent) { inputMove?(inputPoint(event)) }
    override func mouseUp(with event: NSEvent) { inputEnd?(inputPoint(event)) }
    // Returns what it drew, in global points. avoid: more of what the marks point at (a click target); dim: an earlier whiteboard step.
    @discardableResult func render(_ shapes: [DrawingShape], animate: Bool, previous: CGPoint?, append: Bool = false, avoid: [CGRect] = [], dim: Bool = false, step: Int = 0) -> CGRect {
        wantsLayer = true
        if !append { reset() }
        let colors = ScreenDrawing.colors
        func local(_ p: CGPoint) -> CGPoint { CGPoint(x:p.x-origin.x, y:p.y-origin.y) }
        let targets = shapes.compactMap { $0.rect.map(ScreenDrawing.rect) } + avoid
        let keepOff = targets.map { $0.insetBy(dx:-ScreenDrawing.gap,dy:-ScreenDrawing.gap) } + shapes.compactMap { s in s.rect.map { ScreenDrawing.ring(ScreenDrawing.rect($0),circle:s.kind == "circle") } }
        let screen = bounds.offsetBy(dx:origin.x,dy:origin.y)
        var drawn = CGRect.null
        func add(_ l: CALayer, _ frame: CGRect) {
            let global = frame.offsetBy(dx:origin.x,dy:origin.y)
            guard screen.intersects(global) else { return }
            if dim { l.opacity = 0.5 }; layer?.addSublayer(l); drawn = drawn.union(global.intersection(screen))
        }
        func hit(_ area: CGPath, _ shape: Int) {   // strokes take clicks near the line only, so the target inside a ring stays clickable
            if screen.intersects(area.boundingBoxOfPath.offsetBy(dx:origin.x,dy:origin.y)) { hits.append((area,step,shape)) }
        }
        for (i, shape) in shapes.enumerated() where shape.kind != "text" {
            let color = colors[shape.color ?? "red"] ?? .systemRed
            let path = CGMutablePath()
            if let r = shape.rect {
                let bounds = ScreenDrawing.rect(r)
                let frame = (shape.fill == true ? bounds : ScreenDrawing.ring(bounds,circle:shape.kind == "circle")).offsetBy(dx:-origin.x,dy:-origin.y)
                if shape.kind == "circle" { path.addEllipse(in:frame) } else { path.addRoundedRect(in:frame,cornerWidth:6,cornerHeight:6) }
            } else if let points = shape.points?.map({ CGPoint(x:$0[0],y:$0[1]) }), let first = points.first {
                var points = points
                if shape.kind == "arrow" { points[points.count-1] = ScreenDrawing.arrowTip(from:first,to:points[points.count-1],avoiding:targets) }
                path.addLines(between:points.map(local))
                if shape.kind == "arrow", let last = points.last {
                    let p = local(last), angle = atan2(last.y-first.y,last.x-first.x)
                    for delta in [-0.5, 0.5] { path.move(to:p); path.addLine(to:CGPoint(x:p.x-13*cos(angle+delta),y:p.y-13*sin(angle+delta))) }
                }
            } else if let at = shape.at {
                let point = CGPoint(x:at[0],y:at[1])
                if shape.kind == "label" {
                    guard screen.contains(point) else { continue }
                    let light = ["green","yellow","white"].contains(shape.color ?? "red")
                    let font = NSFont.systemFont(ofSize:["s":12,"m":15,"l":19][shape.size ?? "m"] ?? 15,weight:.semibold)
                    let attributes: [NSAttributedString.Key:Any] = [.font:font,.foregroundColor:light ? NSColor.black : NSColor.white]
                    let text = NSAttributedString(string:shape.text ?? "",attributes:attributes)
                    let textSize = text.size(), size = CGSize(width:min(bounds.width-12,textSize.width+16),height:textSize.height+10)
                    // a label set near a mark but off it sits right beside that mark; with an arrow or line it stays where the model put it
                    let edges = shapes.contains { ["arrow","line","path"].contains($0.kind) } ? [] : targets.map { CGPoint(x:min(max(point.x,$0.minX),$0.maxX),y:min(max(point.y,$0.minY),$0.maxY)) }
                    let near = edges.min { hypot($0.x-point.x,$0.y-point.y) < hypot($1.x-point.x,$1.y-point.y) }
                    let anchor = near.map { hypot($0.x-point.x,$0.y-point.y) < 160 ? $0 : point } ?? point
                    let box = ScreenDrawing.labelBox(size,at:anchor,keepOff:keepOff,in:screen.insetBy(dx:6,dy:6)).offsetBy(dx:-origin.x,dy:-origin.y)
                    let bg = CAShapeLayer(); bg.path = CGPath(roundedRect:box,cornerWidth:7,cornerHeight:7,transform:nil); bg.fillColor = (light ? color : color.blended(withFraction:0.2,of:.black) ?? color).cgColor
                    add(bg,box); hit(CGPath(rect:box,transform:nil),i)
                    let label = CATextLayer(); label.string = text; label.contentsScale = window?.backingScaleFactor ?? 2
                    label.frame = CGRect(x:box.minX+8,y:box.midY-textSize.height/2,width:box.width-16,height:textSize.height); label.truncationMode = .end
                    add(label,box); continue
                }
                let p = local(ScreenDrawing.beside(point,targets))
                let dot = CAShapeLayer(); dot.path = CGPath(ellipseIn:CGRect(x:-5,y:-5,width:10,height:10),transform:nil)
                dot.fillColor = color.cgColor; dot.strokeColor = NSColor.white.cgColor; dot.lineWidth = 2; dot.position = p
                add(dot,CGRect(x:p.x-6,y:p.y-6,width:12,height:12)); hit(CGPath(ellipseIn:CGRect(x:p.x-10,y:p.y-10,width:20,height:20),transform:nil),i)
                if animate, let previous {
                    let move = CABasicAnimation(keyPath:"position"); move.fromValue = NSValue(point:CGPoint(x:previous.x-origin.x,y:previous.y-origin.y)); move.toValue = NSValue(point:p); move.duration = 0.25; dot.add(move,forKey:"move")
                }
                continue
            }
            let stroke = CAShapeLayer(); stroke.path = path; stroke.fillColor = shape.fill == true ? color.withAlphaComponent(0.18).cgColor : NSColor.clear.cgColor
            stroke.strokeColor = color.cgColor; stroke.lineWidth = 3; stroke.lineCap = .round; stroke.lineJoin = .round
            stroke.shadowColor = NSColor.black.cgColor; stroke.shadowOpacity = 0.45; stroke.shadowRadius = 2
            add(stroke,path.boundingBoxOfPath.insetBy(dx:-3,dy:-3))
            hit(shape.fill == true ? path : path.copy(strokingWithWidth:12,lineCap:.round,lineJoin:.round,miterLimit:2),i)
            if animate { let draw = CABasicAnimation(keyPath:"strokeEnd"); draw.fromValue = 0; draw.toValue = 1; draw.duration = 0.28; stroke.add(draw,forKey:"draw") }
        }
        return drawn
    }
}

// One step's text beside its marks: a dark card whose notch points at them, with Back / Next.
final class DrawingCalloutView: NSView {
    var onBack: (() -> Void)?, onNext: (() -> Void)?, onClose: (() -> Void)?
    static let font = NSFont.systemFont(ofSize:14,weight:.medium), notch: CGFloat = 7, margin: CGFloat = 12
    override var isFlipped: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    static func size(_ text: String, total: Int) -> CGSize {   // the card alone, without notch or shadow margin
        let measured: CGSize = text.isEmpty ? .zero : (text as NSString).boundingRect(with:CGSize(width:300,height:CGFloat.greatestFiniteMagnitude),
            options:[.usesLineFragmentOrigin,.usesFontLeading],attributes:[.font:font]).size
        let body = text.isEmpty ? 0 : min(240,ceil(measured.height)) + 12
        return CGSize(width:max(total > 1 ? 232 : 180,ceil(measured.width)+33), height:14 + (total > 1 ? 24 : 0) + body + 26 + 14)
    }
    static func bubble(_ card: CGRect, side: NSRectEdge?, tip: CGFloat) -> CGPath {   // flipped coordinates; tip runs along the facing edge
        let p = CGMutablePath(), r: CGFloat = 12, n = notch
        let along = side == .minX || side == .maxX ? (card.minY, card.maxY) : (card.minX, card.maxX)
        let t = min(max(tip,along.0+r+n),along.1-r-n)
        func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x:x,y:y) }
        func tooth(_ points: [CGPoint]) { points.forEach { p.addLine(to:$0) } }   // addLines(between:) would start a new subpath
        p.move(to:pt(card.minX+r,card.minY))
        if side == .minY { tooth([pt(t-n,card.minY),pt(t,card.minY-n),pt(t+n,card.minY)]) }
        p.addArc(tangent1End:pt(card.maxX,card.minY),tangent2End:pt(card.maxX,card.maxY),radius:r)
        if side == .maxX { tooth([pt(card.maxX,t-n),pt(card.maxX+n,t),pt(card.maxX,t+n)]) }
        p.addArc(tangent1End:pt(card.maxX,card.maxY),tangent2End:pt(card.minX,card.maxY),radius:r)
        if side == .maxY { tooth([pt(t+n,card.maxY),pt(t,card.maxY+n),pt(t-n,card.maxY)]) }
        p.addArc(tangent1End:pt(card.minX,card.maxY),tangent2End:pt(card.minX,card.minY),radius:r)
        if side == .minX { tooth([pt(card.minX,t+n),pt(card.minX-n,t),pt(card.minX,t-n)]) }
        p.addArc(tangent1End:pt(card.minX,card.minY),tangent2End:pt(card.maxX,card.minY),radius:r)
        p.closeSubpath(); return p
    }
    init(frame: CGRect, card: CGRect, side: NSRectEdge?, tip: CGFloat, text: String, step: Int, total: Int) {
        super.init(frame: frame)
        wantsLayer = true
        let shape = CAShapeLayer(), path = Self.bubble(card,side:side,tip:tip)
        shape.path = path; shape.fillColor = NSColor(calibratedWhite:0.08,alpha:0.94).cgColor
        shape.strokeColor = NSColor.white.withAlphaComponent(0.22).cgColor; shape.lineWidth = 0.5
        shape.shadowColor = NSColor.black.cgColor; shape.shadowOpacity = 0.35; shape.shadowRadius = 8; shape.shadowOffset = .zero; shape.shadowPath = path
        layer?.addSublayer(shape)
        setAccessibilityElement(true); setAccessibilityRole(.group); setAccessibilityLabel(total > 1 ? "Guide, step \(step) of \(total)" : "Guide")
        var y = card.minY + 14
        if total > 1 {
            let progress = NSTextField(labelWithString:"Step \(step) of \(total)")
            progress.font = .systemFont(ofSize:11,weight:.semibold); progress.textColor = NSColor.white.withAlphaComponent(0.68)
            progress.frame = CGRect(x:card.minX+16,y:y,width:card.width-64,height:16); addSubview(progress)
            let close = NSButton(image:NSImage(systemSymbolName:"xmark",accessibilityDescription:"Close guide") ?? NSImage(),target:self,action:#selector(closeGuide))
            close.isBordered = false; close.contentTintColor = NSColor.white.withAlphaComponent(0.6); close.toolTip = "Close guide"
            close.frame = CGRect(x:card.maxX-34,y:y-1,width:18,height:18); addSubview(close)
            y += 24
        }
        if !text.isEmpty {
            let height = card.maxY - 14 - 26 - 12 - y
            let scroll = NSScrollView(frame:CGRect(x:card.minX+16,y:y,width:card.width-32,height:height))
            scroll.drawsBackground = false; scroll.borderType = .noBorder; scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true
            let body = NSTextView(frame:CGRect(origin:.zero,size:scroll.contentSize))
            body.string = text; body.font = Self.font; body.textColor = .white; body.drawsBackground = false
            body.isEditable = false; body.isSelectable = true; body.textContainerInset = .zero; body.isVerticallyResizable = true
            body.textContainer?.lineFragmentPadding = 0
            body.textContainer?.containerSize = NSSize(width:scroll.contentSize.width,height:.greatestFiniteMagnitude)
            body.textContainer?.widthTracksTextView = true; body.autoresizingMask = [.width]
            scroll.documentView = body; addSubview(scroll)
            y += height + 12
        }
        let last = step >= total
        let next = NSButton(title:last ? "Done" : "Next",target:self,action:#selector(nextStep))
        next.bezelStyle = .rounded; next.bezelColor = .systemBlue; next.frame = CGRect(x:card.maxX-16-68,y:y,width:68,height:26)
        next.setAccessibilityLabel(last ? "Done" : "Next step"); addSubview(next)
        if total > 1 {
            let back = NSButton(title:"Back",target:self,action:#selector(backStep))
            back.bezelStyle = .rounded; back.isEnabled = step > 1; back.frame = CGRect(x:next.frame.minX-8-68,y:y,width:68,height:26)
            back.setAccessibilityLabel("Previous step"); addSubview(back)
        }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    @objc func closeGuide() { onClose?() }
    @objc func nextStep() { onNext?() }
    @objc func backStep() { onBack?() }
}

final class ScreenDrawing {
    var panels: [DrawingPanel] = [], request: DrawingRequest?, index = 0
    var inputPanels: [DrawingPanel] = []   // Point at your screen draws under the guide, so a guide stays up while the user marks
    var calloutPanel: DrawingPanel?
    struct BoardLine { let text: NSAttributedString, rect: CGRect, step: Int, shape: Int }   // global points
    var board: (frame: CGRect, pad: CGFloat, lines: [BoardLine])?
    var selected: (step: Int, shape: Int)?, overMark = false
    var picked: ((CGRect, String) -> Void)?   // a click on a mark: its screen area and what it is
    var changed: (() -> Void)?   // marks appeared, moved or went: the box gets out of their way
    var occupied: [CGRect] = []   // global points the drawing covers: marks, their targets, the step card
    var manual = false   // Back or Next was pressed: auto steps stop for this guide
    var autoSteps: () -> Bool = { true }
    var timer: Timer?, monitors: [Any] = [], voice: Process?, element: AXUIElement?, originalValue: CFTypeRef?
    var target: DrawingWindow?, hit: CGRect?, deadline = Date.distantPast, ready = Date.distantPast, advanceAt = Date.distantPast
    var previousPointer: CGPoint?
    var focus: CGRect?   // the shown step's marks (global points): the box's leader line aims here
    var inputPath: [CGPoint] = [], inputMode = false
    var inputDone: (([CGPoint]) -> Void)?, inputCleared: (() -> Void)?, inputAway: (() -> Void)?
    var resolve: ((String,String) throws -> (CGRect,AXUIElement?,DrawingWindow))?
    var readValue: (AXUIElement) -> CFTypeRef? = { e in
        var value: CFTypeRef?
        return AXUIElementCopyAttributeValue(e,kAXValueAttribute as CFString,&value) == .success ? value : nil
    }
    var cleanup: (() -> Void)?
    var status: ((String) -> Void)?
    var speechEnabled: () -> Bool = { false }
    var active: Bool { request != nil }
    var hasInput: Bool { inputMode || !inputPath.isEmpty }
    var summary: [String:Any]? {   // what is on screen, for the next ask to build on
        guard let r = request, let data = try? JSONEncoder().encode(r.steps), let steps = try? JSONSerialization.jsonObject(with:data) else { return nil }
        return ["steps":steps, "shown":index+1]
    }
    // Readable from a normal distance: about 29 points on a laptop, 32 on a 1080p monitor; s and l scale it.
    static func textSize(_ size: String?, display: CGRect) -> CGFloat { max(22,min(40,display.height/34)) * (["s":0.75,"l":1.4][size ?? ""] ?? 1) }
    // Every text line of the guide on one panel, laid out once so it grows in place: at the first line's `at`, else beside the other marks.
    static let colors: [String:NSColor] = ["red":.systemRed, "blue":.systemBlue, "green":.systemGreen, "yellow":.systemYellow, "white":.white]
    static func board(_ steps: [DrawingStep], near: CGRect) -> (frame: CGRect, pad: CGFloat, lines: [BoardLine])? {
        let texts = steps.enumerated().flatMap { s in s.element.shapes.enumerated().filter { $0.element.kind == "text" }.map { (s.offset,$0.offset,$0.element) } }
        guard let first = texts.first?.2 else { return nil }
        let anchor = first.at.map { CGPoint(x:$0[0],y:$0[1]) } ?? CGPoint(x:near.midX,y:near.midY), top = NSScreen.screens.first?.frame.maxY ?? 0
        func display(_ s: NSScreen) -> CGRect { CGDisplayBounds(s.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()) }
        guard let screen = NSScreen.screens.first(where: { display($0).contains(anchor) }) ?? NSScreen.main ?? NSScreen.screens.first else { return nil }
        let v = screen.visibleFrame, area = CGRect(x:v.minX,y:top-v.maxY,width:v.width,height:v.height).insetBy(dx:12,dy:12)
        let base = textSize(nil,display:display(screen)), pad = round(base*0.7), gap = round(base*0.3), wrap = max(200,min(area.width*0.5,820))
        var y = pad, width: CGFloat = 0, sized: [(NSAttributedString,CGSize,Int,Int)] = []
        for (step,shape,s) in texts {
            let font = NSFont.systemFont(ofSize:textSize(s.size,display:display(screen)),weight:.medium)
            let text = NSAttributedString(string:s.text ?? "",attributes:[.font:font,.foregroundColor:s.color.flatMap { colors[$0] } ?? .white])
            let size = text.boundingRect(with:CGSize(width:wrap,height:.greatestFiniteMagnitude),options:[.usesLineFragmentOrigin,.usesFontLeading]).size
            sized.append((text,CGSize(width:ceil(size.width)+2,height:ceil(size.height)),step,shape)); width = max(width,ceil(size.width)+2)
        }
        let height = sized.reduce(pad) { $0 + $1.1.height + gap } - gap + pad
        let size = CGSize(width:min(area.width,width+2*pad), height:min(area.height,height))
        let origin = first.at.map { CGPoint(x:min(max($0[0],area.minX),area.maxX-size.width), y:min(max($0[1],area.minY),area.maxY-size.height)) }
            ?? calloutFrame(size,marks:near,avoid:[],in:area).card.origin
        let lines = sized.map { line in defer { y += line.1.height + gap }; return BoardLine(text:line.0,rect:CGRect(x:origin.x+pad,y:origin.y+y,width:line.1.width,height:line.1.height),step:line.2,shape:line.3) }
        return (CGRect(origin:origin,size:size), pad, lines)
    }
    // Follow the active step down a long board; Back pages earlier lines into view again.
    static func boardPage(_ board: (frame: CGRect, pad: CGFloat, lines: [BoardLine]), through step: Int) -> (frame: CGRect, lines: [BoardLine])? {
        let shown = board.lines.filter { $0.step <= step }
        guard let last = shown.last else { return nil }
        let offset = max(0, last.rect.maxY + board.pad - board.frame.maxY)
        let viewport = board.frame.insetBy(dx: 0, dy: board.pad)
        let lines = shown.compactMap { line -> BoardLine? in
            let rect = line.rect.offsetBy(dx: 0, dy: -offset)
            return rect.intersects(viewport) ? BoardLine(text: line.text, rect: rect, step: line.step, shape: line.shape) : nil
        }
        guard let visible = lines.last else { return nil }
        let frame = offset > 0 ? board.frame : CGRect(x: board.frame.minX, y: board.frame.minY, width: board.frame.width,
                                                      height: visible.rect.maxY + board.pad - board.frame.minY)
        return (frame, lines)
    }
    static func numbers(_ v: [Double], _ n: Int) -> Bool { v.count == n && v.allSatisfy { $0.isFinite && abs($0) <= 100000 } }
    static func validRect(_ v: [Double]) -> Bool { numbers(v,4) && v[2] > 0 && v[3] > 0 }
    static func rect(_ v: [Double]) -> CGRect { CGRect(x:v[0],y:v[1],width:v[2],height:v[3]) }
    // Marks sit around or beside what they mark, never on it: `gap` is the clear space they keep.
    static let gap: CGFloat = 6
    static func ring(_ r: CGRect, circle: Bool) -> CGRect {   // the 3-point stroke lies outside the target; an ellipse passes outside its corners
        let out = r.insetBy(dx:-(gap+1.5),dy:-(gap+1.5))
        return circle ? out.insetBy(dx:-out.width*(sqrt(2)-1)/2,dy:-out.height*(sqrt(2)-1)/2) : out
    }
    static func arrowTip(from a: CGPoint, to b: CGPoint, avoiding targets: [CGRect]) -> CGPoint {   // the head stops at the target's edge
        guard let box = targets.map({ $0.insetBy(dx:-gap-2,dy:-gap-2) }).first(where: { $0.contains(b) && !$0.contains(a) }) else { return b }
        var lo: CGFloat = 0, hi: CGFloat = 1
        func at(_ s: CGFloat) -> CGPoint { CGPoint(x:a.x+(b.x-a.x)*s,y:a.y+(b.y-a.y)*s) }
        for _ in 0..<24 { let m = (lo+hi)/2; if box.contains(at(m)) { hi = m } else { lo = m } }
        return at(lo)
    }
    static func leader(from box: CGRect, to target: CGRect) -> (CGPoint, CGPoint)? {   // the box edge nearest the target, to just outside it; nil when close
        let aim = CGPoint(x:target.midX,y:target.midY)
        let a = CGPoint(x:min(max(aim.x,box.minX),box.maxX),y:min(max(aim.y,box.minY),box.maxY))
        let b = arrowTip(from:a,to:aim,avoiding:[target])
        return hypot(b.x-a.x,b.y-a.y) > 60 ? (a,b) : nil
    }
    static func beside(_ p: CGPoint, _ targets: [CGRect]) -> CGPoint {   // a pointer on a target rests at its lower-right corner
        guard let t = targets.first(where: { $0.contains(p) }) else { return p }
        return CGPoint(x:t.maxX+gap,y:t.maxY+gap)
    }
    static func labelBox(_ size: CGSize, at p: CGPoint, keepOff: [CGRect], in area: CGRect) -> CGRect {
        var spots = [CGPoint(x:p.x+12,y:p.y-size.height-4), CGPoint(x:p.x+12,y:p.y+8), CGPoint(x:p.x-12-size.width,y:p.y-size.height-4), CGPoint(x:p.x-12-size.width,y:p.y+8)]
        for t in keepOff where t.contains(p) {   // anchored on a target: beside it instead
            spots += [CGPoint(x:t.maxX+4,y:t.midY-size.height/2), CGPoint(x:t.minX-4-size.width,y:t.midY-size.height/2),
                      CGPoint(x:t.midX-size.width/2,y:t.minY-4-size.height), CGPoint(x:t.midX-size.width/2,y:t.maxY+4)]
        }
        func clear(_ box: CGRect) -> Bool {   // outside every mark, or well inside a large one (an area model's "x²"), never across an edge
            area.contains(box) && !keepOff.contains { $0.intersects(box) && !$0.insetBy(dx:2*gap,dy:2*gap).contains(box) }
        }
        if let spot = spots.first(where: { clear(CGRect(origin:$0,size:size)) }) {
            return CGRect(origin:spot,size:size)
        }
        return CGRect(x:max(area.minX,min(area.maxX-size.width,spots[0].x)),y:max(area.minY,min(area.maxY-size.height,spots[0].y)),width:size.width,height:size.height)
    }
    // The card beside the step's marks (right, left, below, above), clear of them and, if it can, of earlier steps; else the far corner.
    static func calloutFrame(_ size: CGSize, marks: CGRect, avoid: [CGRect], in area: CGRect) -> (card: CGRect, side: NSRectEdge?) {
        let g = DrawingCalloutView.notch + 8
        func x(_ v: CGFloat) -> CGFloat { min(max(v,area.minX),area.maxX-size.width) }
        func y(_ v: CGFloat) -> CGFloat { min(max(v,area.minY),area.maxY-size.height) }
        var options: [(CGPoint,NSRectEdge)] = []   // each side centred on the marks, then lined up with their start or end
        for v in [marks.midY-size.height/2, marks.minY, marks.maxY-size.height].map(y) { options += [(CGPoint(x:marks.maxX+g,y:v),.minX), (CGPoint(x:marks.minX-g-size.width,y:v),.maxX)] }
        for v in [marks.midX-size.width/2, marks.minX, marks.maxX-size.width].map(x) { options += [(CGPoint(x:v,y:marks.maxY+g),.minY), (CGPoint(x:v,y:marks.minY-g-size.height),.maxY)] }
        for keep in [avoid + [marks], [marks]] {
            for (origin,side) in options {
                let card = CGRect(origin:origin,size:size)
                if area.contains(card) && !keep.contains(where: { $0.intersects(card) }) { return (card,side) }
            }
        }
        return (CGRect(x:marks.midX < area.midX ? area.maxX-size.width : area.minX, y:marks.midY < area.midY ? area.maxY-size.height : area.minY, width:size.width, height:size.height), nil)
    }
    // The box's spot (Cocoa points): where it is if clear of every mark, else the nearest clear spot fully on any display, else nil (it stays).
    static func clearSpot(_ box: CGRect, avoiding marks: [CGRect], in screens: [CGRect]) -> CGPoint? {
        let keep = marks.map { $0.insetBy(dx:-32,dy:-32) }
        func clear(_ r: CGRect) -> Bool { !keep.contains { $0.intersects(r) } }
        if clear(box) { return box.origin }
        // no fully clear spot: the one covering the least drawing, nearest first
        func covered(_ r: CGRect) -> CGFloat { keep.reduce(0) { let i = $1.intersection(r); return $0 + (i.isNull ? 0 : i.width*i.height) } }
        var best: CGPoint?, distance = CGFloat.infinity, least = covered(box)
        for screen in screens {
            let a = screen.insetBy(dx:8,dy:8)
            guard a.width >= box.width, a.height >= box.height else { continue }
            let xs = [box.minX, a.minX, a.maxX-box.width] + keep.flatMap { [$0.maxX, $0.minX-box.width] }
            let ys = [box.minY, a.minY, a.maxY-box.height] + keep.flatMap { [$0.maxY, $0.minY-box.height] }
            for x in xs where x >= a.minX && x <= a.maxX-box.width {
                for y in ys where y >= a.minY && y <= a.maxY-box.height {
                    let d = hypot(x-box.minX, y-box.minY), c = covered(CGRect(x:x,y:y,width:box.width,height:box.height))
                    if c < least || c == least && best != nil && d < distance { best = CGPoint(x:x,y:y); distance = d; least = c }
                }
            }
        }
        return best
    }
    static func valid(_ r: DrawingRequest) -> Bool {
        guard r.target.valid, (1...12).contains(r.steps.count) else { return false }
        let teaching = r.steps.allSatisfy { $0.wait != true && $0.target == nil && $0.hit == nil }
        guard r.teaching == teaching, !teaching || r.steps.allSatisfy({ $0.say?.isEmpty == false }) else { return false }
        return r.steps.allSatisfy { step in
            guard (1...40).contains(step.shapes.count), (5...120).contains(step.timeout ?? 60), (step.say?.count ?? 0) <= 1000,
                  step.hit.map(validRect) ?? true, step.wait != true || step.target != nil || step.hit != nil else { return false }
            return step.shapes.allSatisfy { s in
                guard ["red","blue","green","yellow","white"].contains(s.color ?? "red"),
                      s.rect == nil || ["rect","circle"].contains(s.kind), s.at == nil || ["pointer","label","text"].contains(s.kind),
                      s.points == nil || ["arrow","line","path"].contains(s.kind), s.text == nil || ["label","text"].contains(s.kind),
                      s.size == nil || ["label","text"].contains(s.kind) && ["s","m","l"].contains(s.size!),
                      s.fill == nil || ["rect","circle"].contains(s.kind) else { return false }
                switch s.kind {
                case "rect","circle": return s.rect.map(validRect) ?? (step.target != nil)
                case "pointer","label": return (s.at.map { numbers($0,2) } ?? (step.target != nil)) && (s.kind != "label" || (1...120).contains(s.text?.count ?? 0))
                case "text": return (s.at.map { numbers($0,2) } ?? true) && (1...300).contains(s.text?.count ?? 0)
                case "arrow","line","path": return s.points.map { (2...(s.kind == "path" ? 256 : 2)).contains($0.count) && $0.allSatisfy { numbers($0,2) } } ?? false
                default: return false
                }
            }
        }
    }
    static func onDisplays(_ r: DrawingRequest) -> Bool {
        let displays = NSScreen.screens.map { screen in CGDisplayBounds(screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()) }
        func point(_ p: [Double]) -> Bool { displays.contains { p[0] >= $0.minX && p[0] <= $0.maxX && p[1] >= $0.minY && p[1] <= $0.maxY } }
        func rect(_ v: [Double]) -> Bool { point([v[0],v[1]]) && point([v[0]+v[2],v[1]+v[3]]) }
        return r.steps.allSatisfy { step in
            (step.hit.map(rect) ?? true) && step.shapes.allSatisfy { shape in
                (shape.at.map(point) ?? true) && (shape.rect.map(rect) ?? true) && (shape.points?.allSatisfy(point) ?? true)
            }
        }
    }
    @discardableResult func receive(_ data: Data) -> Bool {
        guard let r = try? JSONDecoder().decode(DrawingRequest.self,from:data), Self.valid(r), Self.onDisplays(r) else { return false }
        clear(); request = r; index = 0
        board = Self.board(r.steps,near:shapeBounds(r.steps.flatMap { $0.shapes.filter { $0.kind != "text" } }) ?? r.target.bounds)
        let click: (NSEvent) -> Void = { [weak self] event in
            guard let self, event.window !== calloutPanel, !panels.contains(where: { $0 === event.window }), let point = event.cgEvent?.location else { return }   // a click on a mark selects it, never the app under it
            if request?.teaching == true { return }
            guard let target else { return }
            let windows = CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []
            let clickedWindow = windows.first { info in
                guard (info[kCGWindowLayer as String] as? Int) == 0,
                      let bounds = info[kCGWindowBounds as String] as? NSDictionary,
                      let frame = CGRect(dictionaryRepresentation:bounds) else { return false }
                return frame.contains(point)
            }
            guard (clickedWindow?[kCGWindowNumber as String] as? NSNumber)?.stringValue == target.windowID else { return }
            clicked(point)
        }
        if let m = NSEvent.addGlobalMonitorForEvents(matching:.leftMouseDown,handler:click) { monitors.append(m) }
        if let m = NSEvent.addLocalMonitorForEvents(matching:.leftMouseDown,handler:{ e in click(e); return e }) { monitors.append(m) }
        showStep()
        let shown = active && (!r.teaching || calloutPanel?.isVisible == true)
        if let path = r.receipt { try? (shown ? "shown" : "The target changed; read again.").write(toFile:path,atomically:true,encoding:.utf8) }
        if active { timer = Timer.scheduledTimer(withTimeInterval:0.15,repeats:true) { [weak self] _ in self?.tick() } }
        return active
    }
    func clear() {
        let wasActive = active
        timer?.invalidate(); timer = nil; monitors.forEach(NSEvent.removeMonitor); monitors.removeAll()
        stopVoice(); panels.forEach { $0.close() }; panels.removeAll(); calloutPanel?.close(); calloutPanel = nil
        request = nil; target = nil; hit = nil; element = nil; originalValue = nil; previousPointer = nil; focus = nil
        advanceAt = .distantPast; manual = false; board = nil; selected = nil; occupied = []
        if overMark { overMark = false; NSCursor.arrow.set() }
        clearInput()
        cleanup?()
        if wasActive { changed?() }
    }
    func clearInput() {   // the user's own mark only; a guide stays
        let hadInput = hasInput
        inputPanels.forEach { $0.close() }; inputPanels.removeAll()
        inputPath = []; inputMode = false; inputDone = nil
        if hadInput { NSCursor.arrow.set(); inputCleared?() }
    }
    func hold() { stopVoice(); manual = true }   // the user is asking about it: no more talking or stepping on
    func pick(_ point: CGPoint) {
        guard let r = request, let m = panels.lazy.compactMap({ ($0.contentView as? DrawingView)?.mark(at:point) }).first,
              r.steps.indices.contains(m.step), r.steps[m.step].shapes.indices.contains(m.shape) else { return }
        clearInput(); hold()
        selected = (m.step,m.shape); panels.forEach { ($0.contentView as? DrawingView)?.highlight(selected) }
        let step = r.steps[m.step], shape = step.shapes[m.shape]
        picked?(m.bounds, "\(shape.kind)\(shape.text.map { " \"\($0)\"" } ?? "") in step \(m.step+1) of \(r.steps.count)\(step.say.map { ": " + $0 } ?? "")")
    }
    func deselect() {
        guard selected != nil else { return }
        selected = nil; panels.forEach { ($0.contentView as? DrawingView)?.highlight(nil) }
    }
    // Marks take a click only while the pointer is on one; everywhere else clicks reach the user's apps.
    func hoverMarks() {
        guard NSEvent.pressedMouseButtons == 0, let p = CGEvent(source:nil)?.location else { return }
        let mouse = NSEvent.mouseLocation, mine = panels + inputPanels
        let onBox = NSApp?.windows.contains { w in w.isVisible && !w.ignoresMouseEvents && w.frame.contains(mouse) && !mine.contains { $0 === w } } == true   // the box or a card keeps its clicks
        var over = false
        for panel in panels {
            let on = !onBox && (panel.contentView as? DrawingView)?.mark(at:p) != nil
            if panel.ignoresMouseEvents == on { panel.ignoresMouseEvents = !on }
            over = over || on
        }
        if over { NSCursor.pointingHand.set() } else if overMark { NSCursor.arrow.set() }
        overMark = over
    }
    func beginInput(_ done: @escaping ([CGPoint]) -> Void) {
        clearInput(); inputMode = true; inputDone = done
        for screen in NSScreen.screens {
            let displayID = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()
            let panel = DrawingPanel(contentRect:screen.frame,styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
            panel.isReleasedWhenClosed = false
            panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false; panel.ignoresMouseEvents = false; panel.acceptsMouseMovedEvents = true
            panel.hidesOnDeactivate = false; panel.collectionBehavior = [.canJoinAllSpaces,.fullScreenAuxiliary,.ignoresCycle]
            panel.level = NSWindow.Level(rawValue:NSWindow.Level.statusBar.rawValue - 1)   // under Rabik's own panels even after a click raises it: the box, its cards and buttons take their clicks
            applySharing(panel)
            let view = DrawingView(frame:CGRect(origin:.zero,size:screen.frame.size)); view.origin = CGDisplayBounds(displayID).origin
            view.inputStart = { [weak self] in self?.startInput($0) }
            view.inputMove = { [weak self] in self?.moveInput($0) }
            view.inputEnd = { [weak self] in self?.endInput($0) }
            view.inputHover = { [weak self] in self?.hoverInput($0) }
            panel.contentView = view; panel.orderFrontRegardless(); inputPanels.append(panel)
        }
    }
    func startInput(_ point: CGPoint) { guard inputMode else { return }; inputPath = [point]; renderInput() }   // a new stroke replaces the last one
    func moveInput(_ point: CGPoint) {
        guard inputMode, !inputPath.isEmpty else { return }
        if inputPath.count < 256 && hypot(point.x - inputPath.last!.x, point.y - inputPath.last!.y) >= 2 { inputPath.append(point); renderInput() }
    }
    func endInput(_ point: CGPoint) {
        guard inputMode, !inputPath.isEmpty else { return }
        moveInput(point); renderInput(); inputDone?(inputPath)
    }
    func hoverInput(_ point: CGPoint?) {   // once marked, moving off the mark ends pointing; a stroke near it still redraws
        guard inputMode, !inputPath.isEmpty, NSEvent.pressedMouseButtons & 1 == 0 else { return }
        let xs = inputPath.map(\.x), ys = inputPath.map(\.y)
        let near = CGRect(x:xs.min()!,y:ys.min()!,width:xs.max()!-xs.min()!,height:ys.max()!-ys.min()!).insetBy(dx:-60,dy:-60)
        if point.map(near.contains) != true { inputAway?() }
    }
    func finishInput() {   // the mark stays on screen until the ask is sent; clicks reach the user's apps again
        guard inputMode else { return }
        if inputPath.isEmpty { clearInput(); return }
        inputMode = false; inputDone = nil; inputPanels.forEach { $0.ignoresMouseEvents = true }; NSCursor.arrow.set()
    }
    func renderInput() {
        guard let first = inputPath.first else { return }
        let shape = inputPath.count == 1
            ? DrawingShape(kind:"circle",rect:[Double(first.x-8),Double(first.y-8),16,16],color:"red")
            : DrawingShape(kind:"path",points:inputPath.map { [Double($0.x),Double($0.y)] },color:"red")
        for panel in inputPanels { (panel.contentView as? DrawingView)?.render([shape],animate:false,previous:nil) }
    }
    func stopVoice() { if let voice, voice.isRunning { voice.terminate() }; voice = nil }
    func shapeBounds(_ shapes: [DrawingShape]) -> CGRect? {
        var result = CGRect.null
        for shape in shapes {
            if let r = shape.rect { result = result.union(Self.rect(r)) }
            if let p = shape.at { result = result.union(CGRect(x:p[0],y:p[1],width:1,height:1)) }
            for p in shape.points ?? [] { result = result.union(CGRect(x:p[0],y:p[1],width:1,height:1)) }
        }
        return result.isNull ? nil : result
    }
    func showCallout(_ text: String, step: Int, total: Int, marks: CGRect, avoid: [CGRect]) {
        calloutPanel?.close(); calloutPanel = nil
        let screens = NSScreen.screens, top = screens.first?.frame.maxY ?? 0
        func display(_ s: NSScreen) -> CGRect { CGDisplayBounds(s.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()) }
        guard let screen = screens.first(where: { display($0).contains(CGPoint(x:marks.midX,y:marks.midY)) }) ?? NSScreen.main ?? screens.first else { return }
        let v = screen.visibleFrame, area = CGRect(x:v.minX,y:top-v.maxY,width:v.width,height:v.height).insetBy(dx:12,dy:12)
        var size = DrawingCalloutView.size(text,total:total); size.width = min(size.width,area.width); size.height = min(size.height,area.height)
        let (card,side) = Self.calloutFrame(size,marks:marks,avoid:avoid,in:area)
        let frame = card.insetBy(dx:-DrawingCalloutView.margin,dy:-DrawingCalloutView.margin)   // Quartz points; the margin holds the notch and shadow
        let local = card.offsetBy(dx:-frame.minX,dy:-frame.minY)
        let tip = side == .minX || side == .maxX ? marks.midY-frame.minY : marks.midX-frame.minX
        let panel = DrawingPanel(contentRect:CGRect(x:frame.minX,y:top-frame.maxY,width:frame.width,height:frame.height),styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
        panel.isReleasedWhenClosed = false; panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false
        panel.appearance = NSAppearance(named:.darkAqua)
        panel.ignoresMouseEvents = false; panel.hidesOnDeactivate = false; panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces,.fullScreenAuxiliary,.ignoresCycle]; applySharing(panel)
        let callout = DrawingCalloutView(frame:CGRect(origin:.zero,size:frame.size),card:local,side:side,tip:tip,text:text,step:step,total:total)
        callout.onClose = { [weak self] in self?.clear() }
        callout.onNext = { [weak self] in self?.next() }
        callout.onBack = { [weak self] in self?.back() }
        panel.contentView = callout; calloutPanel = panel
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion { panel.orderFrontRegardless() }
        else { panel.alphaValue = 0; panel.orderFrontRegardless(); NSAnimationContext.runAnimationGroup { $0.duration = 0.18; panel.animator().alphaValue = 1 } }
    }
    func showStep(forward: Bool = true) {
        guard let r = request, r.steps.indices.contains(index) else { clear(); return }
        stopVoice(); calloutPanel?.close(); calloutPanel = nil
        let step = r.steps[index]; target = r.target; hit = step.hit.map(Self.rect); element = nil; originalValue = nil
        var shapes = step.shapes
        if let label = step.target {
            do {
                guard let resolve else { clear(); return }
                let (frame,e,window) = try resolve(label,r.state)
                guard Self.validRect([frame.minX,frame.minY,frame.width,frame.height]), window.valid else { clear(); return }
                target = window; hit = frame; element = e
                if let e { originalValue = readValue(e) }
                for i in shapes.indices {
                    if ["rect","circle"].contains(shapes[i].kind), shapes[i].rect == nil { shapes[i].rect = [frame.minX,frame.minY,frame.width,frame.height] }
                    if ["label","pointer"].contains(shapes[i].kind), shapes[i].at == nil { shapes[i].at = [frame.midX,frame.midY] }
                }
            } catch { status?("The screen changed. Ask again to continue."); clear(); return }
        }
        guard let target else { clear(); return }
        if !r.teaching || index == 0 {
            guard Self.current(target) else { clear(); return }
        }
        let animate = forward && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        if panels.count != NSScreen.screens.count {
            panels.forEach { $0.close() }; panels.removeAll()
            for screen in NSScreen.screens {
                let displayID = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()
                let panel = DrawingPanel(contentRect:screen.frame,styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
                panel.isReleasedWhenClosed = false
                panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false; panel.ignoresMouseEvents = true
                panel.hidesOnDeactivate = false; panel.level = .statusBar; panel.collectionBehavior = [.canJoinAllSpaces,.fullScreenAuxiliary,.ignoresCycle]
                applySharing(panel)
                let view = DrawingView(frame:CGRect(origin:.zero,size:screen.frame.size)); view.origin = CGDisplayBounds(displayID).origin
                view.pick = { [weak self] in self?.pick($0) }
                panel.contentView = view; panel.orderFrontRegardless(); panels.append(panel)
            }
        }
        // Each show redraws from scratch, so Back removes this step's marks; a whiteboard keeps earlier steps, quieter.
        var marks = CGRect.null, earlier: [CGRect] = []
        let page = board.flatMap { Self.boardPage($0, through: index) }
        let lines = page?.lines ?? []
        let boardFrame = page?.frame
        for panel in panels {
            guard let view = panel.contentView as? DrawingView else { continue }
            view.reset()
            if r.teaching { earlier += r.steps[..<index].enumerated().map { view.render($0.element.shapes,animate:false,previous:nil,append:true,dim:true,step:$0.offset) }.filter { !$0.isNull } }
            if let boardFrame { view.renderBoard(boardFrame,lines,current:index,animate:animate) }
            marks = marks.union(view.render(shapes,animate:animate,previous:forward ? previousPointer : nil,append:true,avoid:hit.map { [$0] } ?? [],step:index))
            view.highlight(selected)
        }
        if let boardFrame { if lines.contains(where: { $0.step == index }) { marks = marks.union(boardFrame) } else { earlier.append(boardFrame) } }
        guard !marks.isNull else { clear(); return }
        focus = marks
        if let point = shapes.last(where: { $0.kind == "pointer" })?.at { previousPointer = CGPoint(x:point[0],y:point[1]) }
        let now = Date(); deadline = r.teaching ? .distantFuture : now.addingTimeInterval(step.timeout ?? 60); ready = now.addingTimeInterval(0.35)
        let words = step.say ?? ""
        advanceAt = now.addingTimeInterval(max(3,min(12,1.5+Double(words.split(separator:" ").count)/3.5)))   // long enough to read the callout
        if !words.isEmpty || r.steps.count > 1 {
            showCallout(words,step:index+1,total:r.steps.count,marks:marks.isNull ? shapeBounds(shapes) ?? target.bounds : marks,avoid:earlier + (hit.map { [$0] } ?? []))
        }
        if !words.isEmpty, speechEnabled() {
            let p = Process(); p.executableURL = URL(fileURLWithPath:"/usr/bin/say"); p.arguments = ["--",words]
            try? p.run(); voice = p
        }
        let top = NSScreen.screens.first?.frame.maxY ?? 0
        occupied = panels.flatMap { ($0.contentView as? DrawingView)?.hitBounds ?? [] } + [boardFrame, hit].compactMap { $0 }
            + (calloutPanel.map { f in [CGRect(x:f.frame.minX,y:top-f.frame.maxY,width:f.frame.width,height:f.frame.height)] } ?? [])
        changed?()
    }
    func advance() {
        guard let r = request else { return }
        if index+1 < r.steps.count { index += 1; showStep() } else if !r.teaching { clear() }
    }
    func next() {   // the user's Next ("next" by voice or typing too); on the last step it is Done
        guard let r = request else { return }
        manual = true
        if index+1 < r.steps.count { index += 1; showStep() } else { clear() }
    }
    func back() {
        guard request != nil, index > 0 else { return }
        manual = true; index -= 1; showStep(forward:false)
    }
    func clicked(_ point: CGPoint) {
        guard let r = request, Date() >= ready else { return }
        let step = r.steps[index]
        guard step.wait != true || hit?.contains(point) == true else { return }
        advance()
    }
    static func current(_ target: DrawingWindow) -> Bool {
        let infos = CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []
        guard let info = infos.first(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.stringValue == target.windowID && ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == target.pid }),
              let bounds = info[kCGWindowBounds as String] as? NSDictionary, let frame = CGRect(dictionaryRepresentation:bounds), frame == target.bounds else { return false }
        return true
    }
    func tick() {
        guard let r = request, let target else { return }
        hoverMarks()
        if !r.teaching {
            guard Self.current(target) else { status?("The screen changed. Ask again to continue."); clear(); return }
            if Date() >= deadline { clear(); return }
        }
        let step = r.steps[index]
        if step.wait == true, Date() >= ready, let element {
            if let value = readValue(element), let originalValue, !CFEqual(value,originalValue) { advance() }
        } else if step.wait != true, !manual, autoSteps(), index+1 < r.steps.count, Date() >= advanceAt, voice?.isRunning != true { advance() }
    }
}
