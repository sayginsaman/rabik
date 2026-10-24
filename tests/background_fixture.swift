import Cocoa

// A window behind the user's app that logs each event it receives, with who was frontmost and where the pointer was.
let root = CommandLine.arguments[1], log = root + "/background-events.jsonl"

final class Delegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    func applicationDidFinishLaunching(_ n: Notification) {
        window = NSWindow(contentRect: NSRect(x: 200, y: 200, width: 360, height: 220), styleMask: [.titled], backing: .buffered, defer: false)
        window.title = "Background Fixture"
        let pad = NSTextField(labelWithString: "Pad"); pad.frame = NSRect(x: 20, y: 20, width: 320, height: 180); pad.alignment = .center
        window.contentView!.addSubview(pad); window.orderFrontRegardless()
        FileManager.default.createFile(atPath: log, contents: nil)
        let out = FileHandle(forWritingAtPath: log)!
        NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown, .keyDown]) { e in
            let key = e.type == .keyDown
            let row: [String: Any] = ["type": Int(e.type.rawValue), "count": key ? 0 : e.clickCount, "chars": key ? e.charactersIgnoringModifiers ?? "" : "",
                                      "inWindow": e.window === self.window, "x": e.locationInWindow.x, "y": e.locationInWindow.y, "active": NSApp.isActive,
                                      "front": NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0, "pointer": [NSEvent.mouseLocation.x, NSEvent.mouseLocation.y]]
            out.write(try! JSONSerialization.data(withJSONObject: row) + Data("\n".utf8))
            return e
        }
        try? "\(getpid())".write(toFile: root + "/background-ready", atomically: true, encoding: .utf8)
    }
}

let app = NSApplication.shared, delegate = Delegate()
app.setActivationPolicy(.accessory); app.delegate = delegate; app.run()
