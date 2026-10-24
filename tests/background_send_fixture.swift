import Cocoa

final class Fixture: NSObject, NSApplicationDelegate, NSTextFieldDelegate {
    let root = CommandLine.arguments[1]
    let role = CommandLine.arguments[2]
    var window: NSWindow!
    var field: NSTextField!
    var ready = false
    var lostAt: Date?
    var longestLoss = 0.0

    var prefix: String { root + "/" + role }

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: role == "user" ? 60 : 460, y: 120, width: 360, height: 140),
                          styleMask: [.titled], backing: .buffered, defer: false)
        window.title = role == "user" ? "User Work" : role == "agent" ? "Agent Chat" : "Agent Needs Focus"
        window.animationBehavior = .none
        field = NSTextField(frame: NSRect(x: 20, y: 50, width: 320, height: 28))
        field.setAccessibilityLabel(role == "user" ? "Work" : "Prompt")
        field.stringValue = role == "user" ? "BEGIN" : ""
        field.delegate = self
        window.contentView?.addSubview(field)
        window.orderFrontRegardless()
        if role == "user" {
            NSApp.setActivationPolicy(.regular)
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
            window.makeFirstResponder(field)
            field.currentEditor()?.selectedRange = NSRange(location: field.stringValue.utf16.count, length: 0)
        } else {
            NSApp.setActivationPolicy(.accessory)
            window.makeFirstResponder(field)
        }
        Timer.scheduledTimer(withTimeInterval: 0.005, repeats: true) { [weak self] _ in self?.sample() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
            guard let self else { return }
            self.ready = true
            try? String(ProcessInfo.processInfo.processIdentifier).write(toFile: self.prefix + "-ready", atomically: true, encoding: .utf8)
            self.sample()
        }
    }

    func control(_ control: NSControl, textView: NSTextView, doCommandBy commandSelector: Selector) -> Bool {
        guard role != "user", commandSelector == #selector(NSResponder.insertNewline(_:)) else { return false }
        if role == "agent" {
            try? field.stringValue.write(toFile: prefix + "-submitted", atomically: true, encoding: .utf8)
            field.stringValue = ""
        }
        return true
    }

    func controlTextDidChange(_ notification: Notification) { sample() }

    func sample() {
        guard ready else { return }
        let front = NSWorkspace.shared.frontmostApplication?.processIdentifier
        if role == "user" {
            let reset = prefix + "-reset-focus"
            if FileManager.default.fileExists(atPath: reset) {
                longestLoss = 0
                lostAt = nil
                try? FileManager.default.removeItem(atPath: reset)
            }
            if front != ProcessInfo.processInfo.processIdentifier {
                if lostAt == nil { lostAt = Date() }
            } else if let lostAt {
                longestLoss = max(longestLoss, Date().timeIntervalSince(lostAt))
                self.lostAt = nil
            }
        }
        let range = field.currentEditor()?.selectedRange ?? NSRange(location: -1, length: 0)
        let status: [String: Any] = [
            "value": field.stringValue,
            "focused": window.firstResponder === field.currentEditor(),
            "caret": range.location,
            "front": front ?? -1,
            "longestFocusLoss": max(longestLoss, lostAt.map { Date().timeIntervalSince($0) } ?? 0)
        ]
        if let data = try? JSONSerialization.data(withJSONObject: status) {
            try? data.write(to: URL(fileURLWithPath: prefix + "-status"), options: .atomic)
        }
    }
}

let app = NSApplication.shared
let fixture = Fixture()
app.delegate = fixture
app.run()
