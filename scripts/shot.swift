// README screenshots: one of Rabik's real pages (ui/*.html) in an offscreen WKWebView with demo data, framed like the app
// draws it (the box's dark glass, the Settings window, the meeting panel), on a soft backdrop. scripts/readme-shots.py runs it.
// shot <page.html> <handlers,comma> <width> <height> <selector|""> <panel: box|window|meeting|none> <dark 0|1> <script> <out.png>
import Cocoa
import WebKit

let a = CommandLine.arguments
let (page, handlers, width, height, selector, panel, dark, script, out) = (a[1], a[2].split(separator: ",").map(String.init), Double(a[3])!, Double(a[4])!, a[5], a[6], a[7] == "1", a[8], a[9])
final class Sink: NSObject, WKScriptMessageHandler { func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {} }
final class Shot: NSObject, WKNavigationDelegate {
    func webView(_ v: WKWebView, didFinish n: WKNavigation!) {
        let still = "const s=document.createElement('style');s.textContent='*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;transition:none!important}';document.head.append(s);"
        v.callAsyncJavaScript(still + "for(let i=0;i<300&&document.querySelector('script[type=module]')&&!(window.ui||window.st||window.meeting);i++)await new Promise(r=>setTimeout(r,20));\n" + script + "\nawait new Promise(r=>setTimeout(r,900));const e=" + (selector.isEmpty ? "document.body" : "document.querySelector('\(selector)')") + ";const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height];", arguments: [:], in: nil, in: .page) { result in
            guard case .success(let value) = result, let r = value as? [Double] else { print("script failed: \(result)"); exit(1) }
            let c = WKSnapshotConfiguration(); c.rect = NSRect(x: r[0], y: r[1], width: r[2], height: r[3]); c.snapshotWidth = NSNumber(value: r[2] * 2)
            v.takeSnapshot(with: c) { image, error in
                guard let image else { print("snapshot failed: \(String(describing: error))"); exit(1) }
                frame(image, size: NSSize(width: r[2], height: r[3])); exit(0)
            }
        }
    }
}
func frame(_ shot: NSImage, size: NSSize) {
    if panel == "none" {   // the page as drawn, transparent where it is (the README hero composes it itself)
        let rep = NSBitmapImageRep(data: shot.tiffRepresentation!)!
        try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out)); return
    }
    let pad: CGFloat = 56, radius: CGFloat = panel == "window" ? 12 : 18
    let canvas = NSSize(width: size.width + pad * 2, height: size.height + pad * 2), scale: CGFloat = 2
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(canvas.width * scale), pixelsHigh: Int(canvas.height * scale), bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = canvas
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let back = dark ? [NSColor(calibratedRed: 0.16, green: 0.17, blue: 0.24, alpha: 1), NSColor(calibratedRed: 0.32, green: 0.24, blue: 0.36, alpha: 1)]
                    : [NSColor(calibratedRed: 0.86, green: 0.89, blue: 0.97, alpha: 1), NSColor(calibratedRed: 0.97, green: 0.90, blue: 0.92, alpha: 1)]
    NSGradient(colors: back)!.draw(in: NSRect(origin: .zero, size: canvas), angle: -35)
    let box = NSRect(x: pad, y: pad, width: size.width, height: size.height), path = NSBezierPath(roundedRect: box, xRadius: radius, yRadius: radius)
    let shadow = NSShadow(); shadow.shadowBlurRadius = 34; shadow.shadowOffset = NSSize(width: 0, height: -12); shadow.shadowColor = NSColor.black.withAlphaComponent(0.35)
    NSGraphicsContext.saveGraphicsState(); shadow.set()
    (panel == "window" ? (dark ? NSColor(white: 0.12, alpha: 1) : NSColor(white: 0.96, alpha: 1)) : NSColor(calibratedRed: 0.11, green: 0.11, blue: 0.13, alpha: 0.96)).setFill(); path.fill()
    NSGraphicsContext.restoreGraphicsState()
    NSGraphicsContext.saveGraphicsState(); path.addClip(); shot.draw(in: box); NSGraphicsContext.restoreGraphicsState()
    NSColor.white.withAlphaComponent(panel == "window" && !dark ? 0 : 0.12).setStroke(); path.lineWidth = 1; path.stroke()
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
}
let app = NSApplication.shared
let cfg = WKWebViewConfiguration(), sink = Sink(), shot = Shot()
for h in handlers { cfg.userContentController.add(sink, name: h) }
let view = WKWebView(frame: NSRect(x: 0, y: 0, width: width, height: height), configuration: cfg)
view.setValue(false, forKey: "drawsBackground"); view.appearance = NSAppearance(named: dark ? .darkAqua : .aqua); view.navigationDelegate = shot
let root = URL(fileURLWithPath: page).deletingLastPathComponent()
let orbs = (try? String(contentsOf: root.appendingPathComponent("orbs.js"), encoding: .utf8)) ?? ""
view.loadHTMLString(try! String(contentsOfFile: page, encoding: .utf8).replacingOccurrences(of: "/*ORBS*/", with: orbs), baseURL: root)
DispatchQueue.main.asyncAfter(deadline: .now() + 30) { print("timeout"); exit(1) }
app.run()
