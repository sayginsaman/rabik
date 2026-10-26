// Video captures: Rabik's real pages (ui/*.html) in an offscreen WKWebView, the engine the app draws them with, fed demo data from
// video/fixtures. Adapted from scripts/shot.swift; this one also measures elements, so spotlights and overlays land on them.
// capture <shots.json> <out dir> [id ...]   (ids: only those shots)
// Each shot writes <id>.png (the panel alone, transparent outside its rounded corners, at `scale`) and <id>.json:
// {size:[w,h], scale, regions:{name:[x,y,w,h] | [[x,y,w,h], ...]}, styles:{name:{...}}} in points relative to the panel.
import Cocoa
import WebKit

struct Shot: Decodable {
    let id: String, page: String, width: Double, height: Double, root: String, panel: String, dark: Bool, scale: Double
    let fixture: String, regions: [String: String]?, styles: [String: String]?
}
let args = CommandLine.arguments
let jobFile = URL(fileURLWithPath: args[1]), outDir = URL(fileURLWithPath: args[2]), only = Set(args.dropFirst(3))
let base = jobFile.deletingLastPathComponent()
let repo = base.deletingLastPathComponent().deletingLastPathComponent()
let shots = try! JSONDecoder().decode([Shot].self, from: Data(contentsOf: jobFile)).filter { only.isEmpty || only.contains($0.id) }

final class Sink: NSObject, WKScriptMessageHandler { func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {} }
let sink = Sink()

// Freeze CSS motion, wait for the page's API object, run the fixture, then measure the root and the named regions.
func measureJS(_ s: Shot, fixture: String) -> String {
    let regions = (try? String(data: JSONEncoder().encode(s.regions ?? [:]), encoding: .utf8)) ?? "{}"
    let styles = (try? String(data: JSONEncoder().encode(s.styles ?? [:]), encoding: .utf8)) ?? "{}"
    return """
    const still=document.createElement('style');still.textContent='*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;transition:none!important;caret-color:transparent!important}';document.head.append(still);
    for(let i=0;i<300&&document.querySelector('script[type=module]')&&!(window.ui||window.st||window.meeting||window.agents);i++)await new Promise(r=>setTimeout(r,20));
    \(fixture)
    await new Promise(r=>setTimeout(r,1200));
    document.getAnimations().forEach(a=>{try{a.finish()}catch{}});await new Promise(r=>setTimeout(r,100));   // offscreen WebKit never ticks Web Animations
    const root=document.querySelector(\(json(s.root)))||document.body, o=root.getBoundingClientRect();
    const box=e=>{const r=e.getBoundingClientRect();return [r.x-o.x,r.y-o.y,r.width,r.height];};
    const regions={};for(const [k,sel] of Object.entries(\(regions))){
      if(k.endsWith('[]'))regions[k.slice(0,-2)]=[...document.querySelectorAll(sel)].filter(e=>e.getClientRects().length).map(box);
      else{const e=document.querySelector(sel);if(e&&e.getClientRects().length)regions[k]=box(e);}}
    const styles={};for(const [k,sel] of Object.entries(\(styles))){const e=document.querySelector(sel);if(!e)continue;const c=getComputedStyle(e);
      styles[k]={fontFamily:c.fontFamily,fontSize:c.fontSize,fontWeight:c.fontWeight,lineHeight:c.lineHeight,color:c.color,letterSpacing:c.letterSpacing,paddingLeft:c.paddingLeft,paddingTop:c.paddingTop,paddingRight:c.paddingRight,textAlign:c.textAlign};}
    return JSON.stringify({rect:[o.x,o.y,o.width,o.height],regions,styles});
    """
}
func json(_ s: String) -> String { String(data: try! JSONSerialization.data(withJSONObject: s, options: .fragmentsAllowed), encoding: .utf8)! }

// The panel the app draws behind the page: the box's and meeting's dark glass, the Settings window, or nothing.
func compose(_ shot: NSImage, size: NSSize, s: Shot) -> Data {
    let scale = CGFloat(s.scale)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int((size.width * scale).rounded()), pixelsHigh: Int((size.height * scale).rounded()),
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = size
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let rect = NSRect(origin: .zero, size: size)
    if s.panel == "none" { shot.draw(in: rect) } else {
        let radius: CGFloat = s.panel == "window" ? 12 : 18, path = NSBezierPath(roundedRect: rect.insetBy(dx: 0.5, dy: 0.5), xRadius: radius, yRadius: radius)
        (s.panel == "window" ? (s.dark ? NSColor(white: 0.12, alpha: 1) : NSColor(white: 0.96, alpha: 1)) : NSColor(calibratedRed: 0.11, green: 0.11, blue: 0.13, alpha: 0.96)).setFill(); path.fill()
        NSGraphicsContext.saveGraphicsState(); path.addClip(); shot.draw(in: rect); NSGraphicsContext.restoreGraphicsState()
        (s.panel == "window" && !s.dark ? NSColor(srgbRed: 0.89, green: 0.86, blue: 0.82, alpha: 1) : NSColor.white.withAlphaComponent(0.12)).setStroke(); path.lineWidth = 1; path.stroke()
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

final class Runner: NSObject, WKNavigationDelegate {
    var queue = shots, view: WKWebView?, current: Shot?
    func next() {
        guard let s = queue.first else { exit(0) }
        queue.removeFirst(); current = s
        let cfg = WKWebViewConfiguration()
        for h in ["h", "c", "meeting", "st", "agents", "shelf", "view"] { cfg.userContentController.add(sink, name: h) }
        let v = WKWebView(frame: NSRect(x: 0, y: 0, width: s.width, height: s.height), configuration: cfg)
        v.setValue(false, forKey: "drawsBackground"); v.appearance = NSAppearance(named: s.dark ? .darkAqua : .aqua); v.navigationDelegate = self
        let page = repo.appendingPathComponent(s.page), root = page.deletingLastPathComponent()
        let orbs = (try? String(contentsOf: root.appendingPathComponent("orbs.js"), encoding: .utf8)) ?? ""
        view = v
        v.loadHTMLString(try! String(contentsOf: page, encoding: .utf8).replacingOccurrences(of: "/*ORBS*/", with: orbs), baseURL: root)
    }
    func webView(_ v: WKWebView, didFinish n: WKNavigation!) {
        let s = current!, fixture = try! String(contentsOf: base.appendingPathComponent(s.fixture), encoding: .utf8)
        v.callAsyncJavaScript(measureJS(s, fixture: fixture), arguments: [:], in: nil, in: .page) { result in
            guard case .success(let value) = result, let text = value as? String,
                  let info = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any], let r = info["rect"] as? [Double] else {
                print("\(s.id): script failed: \(result)"); exit(1) }
            let c = WKSnapshotConfiguration(); c.rect = NSRect(x: r[0], y: r[1], width: r[2], height: r[3]); c.snapshotWidth = NSNumber(value: r[2] * s.scale)
            v.takeSnapshot(with: c) { image, error in
                guard let image else { print("\(s.id): snapshot failed: \(String(describing: error))"); exit(1) }
                let size = NSSize(width: r[2], height: r[3])
                try! compose(image, size: size, s: s).write(to: outDir.appendingPathComponent("\(s.id).png"))
                let meta: [String: Any] = ["id": s.id, "page": s.page, "size": [r[2], r[3]], "scale": s.scale, "panel": s.panel,
                                           "regions": info["regions"] ?? [:], "styles": info["styles"] ?? [:]]
                try! JSONSerialization.data(withJSONObject: meta, options: [.prettyPrinted, .sortedKeys]).write(to: outDir.appendingPathComponent("\(s.id).json"))
                print("captured \(s.id) \(Int(r[2]))x\(Int(r[3]))pt")
                self.next()
            }
        }
    }
}
let app = NSApplication.shared
let runner = Runner()
DispatchQueue.main.async { runner.next() }
DispatchQueue.main.asyncAfter(deadline: .now() + 240) { print("timeout"); exit(1) }
app.run()
