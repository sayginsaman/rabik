// The welcome and setup window. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// First-run window (ui/onboarding.html): welcome, then each macOS permission with an Allow button, then how to use it.
// Shows until finished once; to see it again: defaults delete com.rabik.app onboarded, then restart the app.
final class Onboarding: NSObject, WKScriptMessageHandler, NSWindowDelegate {
    var win: NSWindow?, web: WKWebView?, timer: Timer?
    var checkingPlan = false
    var screenInitiallyGranted = false, screenGrantedDuringSetup = false
    let pane = "x-apple.systempreferences:com.apple.preference.security?Privacy_"

    func open() {
        guard win == nil else { win?.makeKeyAndOrderFront(nil); return }
        screenInitiallyGranted = CGPreflightScreenCaptureAccess(); screenGrantedDuringSetup = false
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 640),
                         styleMask: [.titled, .closable, .fullSizeContentView], backing: .buffered, defer: false)
        applySharing(w)
        w.titlebarAppearsTransparent = true; w.titleVisibility = .hidden; w.isMovableByWindowBackground = true
        w.isReleasedWhenClosed = false; w.delegate = self
        let bg = NSVisualEffectView(frame: w.contentRect(forFrameRect: w.frame))
        bg.material = .underWindowBackground; bg.blendingMode = .behindWindow; bg.state = .active
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "ob")
        let v = WKWebView(frame: NSRect(x: 0, y: 0, width: 640, height: 612), configuration: cfg)   // top 28 pt stays draggable
        v.setValue(false, forKey: "drawsBackground")
        loadPage(v, "onboarding.html")
        bg.addSubview(v); w.contentView = bg
        win = w; web = v
        w.center(); NSApp.activate(ignoringOtherApps: true); w.makeKeyAndOrderFront(nil)
        var tick = 0
        timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in   // keys 20×/s, permissions 1×/s
            guard let self else { return }
            call("ob.keys", shortcutModifierLabel(NSEvent.modifierFlags))
            tick += 1
            if tick % 20 == 1 { push() }
            if tick % 100 == 1 { checkPlan() }   // every 5 s: it starts Claude Code, too slow for every second
        }
    }

    // Which permissions are on, sent to the page every second (System Settings changes them behind our back).
    func push() {
        DispatchQueue.global().async { [weak self] in
            let s = Onboarding.perms()
            DispatchQueue.main.async {
                if self?.screenInitiallyGranted == false, s["screen"] == true { self?.screenGrantedDuringSetup = true }
                self?.call("ob.set", s)
                self?.web?.evaluateJavaScript("ob.mode(\(Prefs.str("talkMode") == "toggle"))")
                self?.call("ob.prefs", ["meeting": Prefs.bool("meeting"), "draw": Prefs.bool("draw"), "routing": Prefs.str("routing"), "hotkeyLabel": Prefs.str("hotkeyLabel"), "safe": Prefs.bool("safe"),
                                        "dictateMode": Prefs.str("dictateMode"), "dictateHotkeyLabel": Prefs.str("dictateHotkeyLabel"), "globeTaken": globeKeyTaken()])
                self?.call("ob.server", ["apiBase": Prefs.str("apiBase"), "apiModel": Prefs.str("apiModel")])
            }
        }
    }

    static func perms() -> [String: Bool] {
        ["mic": AVCaptureDevice.authorizationStatus(for: .audio) == .authorized, "speech": SFSpeechRecognizer.authorizationStatus() == .authorized,
         "ax": AXIsProcessTrusted(), "screen": CGPreflightScreenCaptureAccess(), "auto": Apps.statuses(["com.apple.systemevents"])["com.apple.systemevents"] == "allowed",
         "calendar": EKEventStore.authorizationStatus(for: .event) == .fullAccess, "tools": Prefs.bool("agentUserTools"),
         "chrome": Prefs.bool("pageJS") || NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.google.Chrome") == nil]   // no Chrome: nothing to turn on   // a live check fails while System Events is quit, so fall back to what was granted
    }

    // Claude Code installed, signed in, on a paid plan? (rabik.py --check)
    static func plan(_ done: @escaping ([String: Any]) -> Void) {
        DispatchQueue.global().async {
            let p = py(["--check"]), out = Pipe(); p.standardOutput = out
            try? p.run(); let data = out.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()   // read first: a full pipe never lets the helper exit
            let j = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            DispatchQueue.main.async { done(j ?? ["ok": false, "need": "install", "text": "Could not run Rabik’s helper (python3 missing?)."]) }
        }
    }

    func checkPlan() {
        guard !checkingPlan else { return }
        checkingPlan = true
        Onboarding.plan { [weak self] c in
            self?.checkingPlan = false
            self?.call("ob.plan", c)
        }
    }

    // The plan row's button: install the AI client, sign in, or upgrade, in a Terminal window the user can watch.
    func fixPlan() {
        Onboarding.plan { [weak self] c in
            let need = c["need"] as? String ?? ""
            let devin = (c["client"] as? String) == "devin", pi = (c["client"] as? String) == "pi", server = (c["client"] as? String) == "server"
            if need == "upgrade" { NSWorkspace.shared.open(URL(string: "https://claude.ai/upgrade")!); return }
            let cmd = need == "install"
                ? devin ? "curl -fsSL https://cli.devin.ai/install.sh | bash && devin auth login"
                        : pi ? "curl -fsSL https://pi.dev/install.sh | sh && echo 'In Pi, use /login or /model to choose your provider.' && pi"
                             : "curl -fsSL https://claude.ai/install.sh | bash" + (server ? "" : " && ~/.local/bin/claude auth login")   // a custom server needs Claude Code, not a Claude account
                : devin ? "devin auth login" : pi ? "echo 'In Pi, use /login or /model to choose your provider.' && pi" : "claude auth login"
            let title = devin ? "Devin" : pi ? "Pi" : "Claude Code"
            let f = NSTemporaryDirectory() + "rabik-\(devin ? "devin" : pi ? "pi" : "claude").command"
            try? "#!/bin/zsh\nexport PATH=\"$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\"\necho 'Rabik: setting up \(title)'\n\(cmd)\necho; echo 'Done. You can close this window.'\n".write(toFile: f, atomically: true, encoding: .utf8)
            chmod(f, 0o755)
            NSWorkspace.shared.open(URL(fileURLWithPath: f))
            self?.checkPlan()
        }
    }

    func tried() { web?.evaluateJavaScript("ob.tried()") }

    // Open the exact privacy pane and point at the switch: Rabik's own row, or an app's row under Rabik (Automation).
    func settings(_ p: String, point label: String = Onboarding.name) {
        NSWorkspace.shared.open(URL(string: pane + p)!)
        Onboarding.pointSwitch(label, under: label == Onboarding.name ? nil : Onboarding.name)
    }
    static let name = Bundle.main.object(forInfoDictionaryKey: "CFBundleName") as? String ?? "Rabik"

    // Show, don't tell: once the pane is up, ring the switch on the row named `label` (below `under`, when given).
    // Reading System Settings needs Accessibility; without it the pane still opens and the card says what to flip.
    static func pointSwitch(_ label: String, under: String? = nil) {
        DispatchQueue.global().async {
            for _ in 0..<16 {
                Thread.sleep(forTimeInterval: 0.5)   // the pane draws its list a moment after it opens
                guard AXIsProcessTrusted(), let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.systempreferences").first else { continue }
                var queue = [AXUIElementCreateApplication(app.processIdentifier)], i = 0, texts: [CGRect] = [], switches: [CGRect] = [], top = -CGFloat.greatestFiniteMagnitude
                while i < queue.count && i < 4000 {
                    let e = queue[i]; i += 1
                    let role = Hands.attribute(e, kAXRoleAttribute) as? String ?? ""
                    if role == "AXStaticText", let v = Hands.attribute(e, kAXValueAttribute) as? String {
                        if v == label { texts.append(Hands.frame(e)) } else if v == under { top = max(top, Hands.frame(e).minY) }
                    }
                    if role == "AXCheckBox" || role == "AXSwitch" { switches.append(Hands.frame(e)) }
                    queue += Hands.children(e)
                }
                guard let row = texts.filter({ $0.minY > top && $0.width > 0 }).min(by: { $0.minY < $1.minY }),
                      let sw = switches.filter({ abs($0.midY - row.midY) < 16 && $0.minX > row.maxX }).min(by: { $0.minX > $1.minX }) else { continue }
                DispatchQueue.main.async { pointAt("@ \(sw.midX) \(sw.midY)") }
                return
            }
        }
    }

    static func bundle(_ app: String) -> String? {
        NSWorkspace.shared.runningApplications.first { $0.localizedName == app }?.bundleIdentifier
            ?? NSWorkspace.shared.fullPath(forApplication: app).flatMap { Bundle(path: $0)?.bundleIdentifier }
    }

    // An agent's "needs you" kinds (rabik.py NEEDS), checked live while its card waits.
    static func granted(_ need: String, app: String) -> Bool {
        if need == "automation" { return bundle(app).map { Apps.check($0, ask: false) == noErr } ?? false }
        return perms()[["accessibility": "ax", "screen": "screen", "microphone": "mic", "calendar": "calendar"][need] ?? ""] ?? false
    }

    // Enable All: Rabik's own settings at once, then each macOS switch in turn, opened and pointed at; what is on is skipped.
    var walk: [String] = [], walkTimer: Timer?, walkSince = Date()
    func enableAll(connected: Bool) {
        grant("tools")
        let p = Onboarding.perms()
        walk = ["ax", "auto", "chrome", "screen", "calendar"].filter { p[$0] != true } + (connected ? [] : ["connectors"])   // page reading needs the first two
        if walk.isEmpty { Rabik.settings.send("notice", ["text": "Everything is already on."]) }   // a click must always answer
        step()
        walkTimer?.invalidate()
        walkTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] t in
            guard let self, let id = walk.first else { t.invalidate(); return }
            DispatchQueue.global().async {
                let on = Onboarding.perms()[id] == true
                DispatchQueue.main.async {   // on, or two minutes without it: the next one
                    if self.walk.first == id, on || Date().timeIntervalSince(self.walkSince) > 120 { self.walk.removeFirst(); self.step() }
                }
            }
        }
    }
    func step() {
        let id = walk.first ?? ""; walkSince = Date()
        call("ob.walk", id); Rabik.settings.send("walk", id)
        switch id {
        case "": break
        case "auto":   // System Events, which page reading and app scripting go through
            DispatchQueue.global().async { if Apps.check("com.apple.systemevents", ask: true) != noErr { DispatchQueue.main.async { self.settings("Automation", point: "System Events") } } }
        case "connectors": grant(id); walk.removeAll(); step()   // signing in happens on claude.ai; its row updates when Settings or setup opens again
        default: grant(id)
        }
    }
    func call(_ f: String, _ v: Any) { callJS(web, f, [v]) }

    // The user's claude.ai connectors (rabik.py --connectors): {connected: [names], signin: [names]}. Slow (it checks each one), so once per open.
    static func connectors(_ done: @escaping ([String: Any]) -> Void) {
        DispatchQueue.global().async {
            let p = py(["--connectors"]), out = Pipe(); p.standardOutput = out
            try? p.run(); let data = out.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()   // read first: a full pipe never lets the helper exit
            let j = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            DispatchQueue.main.async { done(j ?? ["connected": [], "signin": []]) }
        }
    }

    func allow(_ need: String, app: String) {
        switch need {
        case "accessibility": grant("ax")
        case "screen": grant("screen")
        case "microphone": grant("mic")
        case "calendar": grant("calendar")
        case "automation":   // macOS's own prompt if it never asked; its switch under Rabik once it said no
            guard let id = Onboarding.bundle(app) else { return settings("Automation", point: app) }
            DispatchQueue.global().async { if Apps.check(id, ask: true) != noErr { DispatchQueue.main.async { self.settings("Automation", point: app) } } }
        default: break
        }
    }

    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard m.frameInfo.isMainFrame else { return }   // the page itself, never a frame inside it
        guard let b = m.body as? [String: String] else { return }
        if b["do"] == "done" { return finish() }
        if b["do"] == "feedback" { Rabik.settings.open(tab: "feedback"); return }
        if b["do"] == "enableAll" { return enableAll(connected: b["connected"] == "true") }
        if b["do"] == "provider", let c = b["client"], ["claude", "devin", "pi"].contains(c) {   // the plan row's Change provider sheet
            Rabik.settings.apply("client", c)
            for k in ["apiBase", "apiKey", "apiModel"] { if let v = b[k] { Rabik.settings.apply(k, v) } }
            Rabik.settings.push(); return checkPlan()
        }
        if b["do"] == "probe", let base = b["base"] {   // a server typed in the sheet, not saved yet: its models
            return DispatchQueue.global().async { [weak self] in
                let p = py(["--models"], ["RABIK_PROBE_BASE": base, "RABIK_PROBE_KEY": (b["key"] ?? "").isEmpty && base == Prefs.str("apiBase") ? Prefs.str("apiKey") : b["key"] ?? ""]), out = Pipe(); p.standardOutput = out
                try? p.run(); let d = out.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
                let list = (try? JSONSerialization.jsonObject(with: d)) as? [String] ?? []
                DispatchQueue.main.async { self?.call("ob.models", list) }
            }
        }
        if b["do"] == "localServers" { return detectLocalServers { [weak self] found in self?.call("ob.local", found) } }
        if b["do"] == "connectors" { return Onboarding.connectors { [weak self] c in self?.call("ob.connectors", c) } }
        if b["do"] == "set", let k = b["k"], let v = b["v"] {   // the feature pages' switches and choices
            let choices = ["routing": ["cheapest", "balanced", "capable"], "dictateMode": ["verbatim", "cleanup"]]
            if ["meeting", "draw", "improve"].contains(k) { Rabik.settings.apply(k, v == "true") } else if choices[k]?.contains(v) == true { Rabik.settings.apply(k, v) } else { return }
            Rabik.settings.push(); return push()
        }
        if b["do"] == "recordDictate" { return Rabik.settings.record("dictate") { [weak self] call in self?.web?.evaluateJavaScript("ob." + call) } }
        if let d = b["do"], ["cancelRecord", "clearDictate", "globeKey"].contains(d) { Rabik.settings.handle(["do": d]); return push() }
        grant(b["id"] ?? "")
    }

    // A permission's Allow button, from setup or Settings. One click shows one thing: macOS's own box the first time
    // (its button lands on the right list), System Settings once macOS won't ask again. Both at once confused people.
    func grant(_ id: String) {
        switch id {
        case "mic":
            if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined { AVCaptureDevice.requestAccess(for: .audio) { _ in } }
            else { settings("Microphone") }
        case "speech":
            if SFSpeechRecognizer.authorizationStatus() == .notDetermined { SFSpeechRecognizer.requestAuthorization { _ in } }
            else { settings("SpeechRecognition") }
        case "ax":
            if UserDefaults.standard.bool(forKey: "askedAX") { if !AXIsProcessTrusted() { settings("Accessibility") } }
            else { UserDefaults.standard.set(true, forKey: "askedAX"); _ = AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary) }
        case "claude":
            fixPlan()
        case "connectors": NSWorkspace.shared.open(URL(string: "https://claude.ai/settings/connectors")!)
        case "tools": Rabik.settings.apply("agentUserTools", true); Rabik.settings.push()
        case "calendar":
            if EKEventStore.authorizationStatus(for: .event) == .notDetermined { calendar.requestFullAccessToEvents { _, _ in } }
            else { settings("Calendars") }
        case "screen":
            // First click: only macOS's own prompt (its button lands on the right list). Opening Settings at the
            // same time put people in the wrong section; later clicks, when macOS won't prompt again, open Settings.
            if UserDefaults.standard.bool(forKey: "askedScreen") { if !CGPreflightScreenCaptureAccess() { settings("ScreenCapture") } }
            else { UserDefaults.standard.set(true, forKey: "askedScreen"); if CGRequestScreenCaptureAccess() { screenGrantedDuringSetup = true } }
        case "auto":
            Rabik.settings.open(tab: "apps")
        case "chrome":   // clicks Chrome's View > Developer > Allow JavaScript from Apple Events; Rabik keeps it on after this OK
            DispatchQueue.global().async {
                let p = py(["--allow-js"]); try? p.run(); p.waitUntilExit()
                if p.terminationStatus == 0 { DispatchQueue.main.async { Prefs.set("pageJS", true) } }
            }
        default: break
        }
    }

    // Screen Recording only takes effect after a relaunch; launchd (KeepAlive) starts us again right away.
    func finish() {
        UserDefaults.standard.set(true, forKey: "onboarded")
        let relaunch = screenGrantedDuringSetup
        win?.close()
        if relaunch { relaunchSoon() }
    }

    func windowDidResignKey(_ n: Notification) { if Rabik.settings.echo != nil { Rabik.settings.done(nil) } }   // keys typed elsewhere must not become the shortcut

    func windowWillClose(_ n: Notification) {
        if Rabik.settings.echo != nil { Rabik.settings.done(nil) }   // closed mid-recording: keep the old shortcut
        timer?.invalidate(); timer = nil
        walkTimer?.invalidate(); walkTimer = nil   // closing setup cancels Enable All: no more Settings panes open later
        if !walk.isEmpty { walk = []; Rabik.settings.send("walk", "") }
        web?.configuration.userContentController.removeScriptMessageHandler(forName: "ob")
        web = nil; win = nil
    }
}
