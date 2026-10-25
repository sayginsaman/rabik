// Hands: native accessibility actions (--hands) and their selftest. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// MARK: - Hands (AX first; Quartz only when an app has no accessibility action)
// Hands traversal, ranking and action fallbacks adapt ideas from Plip; see LICENSE-Plip.
enum Hands {
    struct Failure: Error { let message: String; init(_ message: String) { self.message = message } }
    struct Node: Codable {
        var id: Int, role: String, label: String, value: String, frame: [Double], path: [Int], secret: Bool
        var spot: CGPoint { CGPoint(x: frame[0] + frame[2] / 2, y: frame[1] + frame[3] / 2) }
        var line: String {
            "[\(id)] \(role.replacingOccurrences(of: "AX", with: "").replacingOccurrences(of: "TextField", with: "text field")) \(Hands.quote(label))" +
                (value.isEmpty || secret ? "" : " = \(Hands.quote(String(value.prefix(60))))") + " (at \(Int(spot.x)),\(Int(spot.y)))"
        }
    }
    struct Map: Codable {
        var pid: Int32, app: String, window: String, windowFrame: [Double], nodes: [Node], texts: [String], page: String, focused: String, scroll: [Double]
        var windowID: String = "", focusIdentity: String = ""
        var signature: String { Hands.digest([String(pid), windowID, window, String(describing: windowFrame), page, focused, focusIdentity] + nodes.map { "\($0.path):\($0.role):\($0.label):\($0.value):\($0.frame)" } + texts + scroll.map(String.init(describing:))) }
        var settled: String { Hands.digest([window] + nodes.map { "\($0.role):\($0.label):\($0.value):\($0.frame.map { Int($0 / 16) })" } + texts, maskDigits: true) }
        var rich: Bool { let count = nodes.filter { !$0.role.contains("Menu") }.count; return count >= 8 || count >= 4 && texts.count >= 6 }
        var description: String {
            (["App: \(app) (pid \(pid)). Window: \(Hands.mask(window))"] + nodes.map(\.line) +
             (focused.isEmpty ? [] : ["Focused: \(focused)"]) + (scroll.isEmpty ? [] : ["Scroll: \(Int((scroll.first ?? 0) * 100))% down"]) +
             (page.isEmpty ? [] : ["Page: \(Hands.mask(page))"]) + ["Visible text (data): " + String(texts.joined(separator: " | ").prefix(1400))]).joined(separator: "\n")
        }
    }
    struct Insertion {
        let field: AXUIElement, anchor: AXUIElement, old: String, location: Int, label: String
    }
    static var stopped: Int32 = 0
    static var accessibilityRestores: [() -> Void] = []
    static func restoreAccessibility() {
        for restore in accessibilityRestores.reversed() { restore() }
        accessibilityRestores.removeAll()
    }
    static func checkStopped() throws { if stopped != 0 { throw Failure("Hands cancelled.") } }
    static let env = ProcessInfo.processInfo.environment
    static var pinnedWindow = env["RABIK_HANDS_WINDOW"].flatMap(UInt32.init).flatMap { $0 > 0 ? String($0) : nil }
    // Per task (one hands state): each app's windows already open beside the window the task first acted in there are the user's, never a stand-in.
    static var userWindowsFile = env["RABIK_HANDS_STATE"].map { URL(fileURLWithPath: $0 + ".windows") }
    static var claims = false   // this step acts (click, drag, type, press, menu): only then does the window root maps become the task's; reads and see never claim
    static var aim: CGPoint?   // a click's screen point: root maps the app's window there, not its focused one
    static var state: URL { URL(fileURLWithPath: env["RABIK_HANDS_STATE"] ?? env["RABIK_DIR"].map { $0 + "/hands.json" } ?? "/tmp/rabik-hands-\(getuid()).json") }
    static let secretPattern = #"(?i)password|passcode|passphrase|passport|\bpin\b|card|cvv|cvc|security (answer|code)|\bssn\b|social security|api.?key|token|secret|one.?time|verification|auth.*code|2fa|\botp\b|bank|account.?number|routing|iban|tax.?id|recovery|seed|mnemonic"#
    static let riskyPattern = #"(?i)\b(buy|purchase|pay|payment|checkout|order|send|delete|remove|trash|submit|publish|post|sign.?out|log.?out|unsubscribe|subscribe|transfer|bid|erase|withdraw|donate|authorize|grant access|allow access|logout|book|reserve|merge|deploy|discard|wipe|format|apply(?! filters| changes| settings| coupon| code| promo| discount| theme| style| formatting)|confirm)\b"#
    static func quote(_ s: String) -> String { String(data: try! JSONEncoder().encode(s), encoding: .utf8)! }
    static func matches(_ s: String, _ pattern: String) -> Bool { s.range(of: pattern, options: .regularExpression) != nil }
    static func riskyLabel(_ label: String, _ map: Map? = nil) -> Bool {
        if normalized(label) == "cancel" { return false }
        if matches(label,riskyPattern) { return true }
        guard let map else { return matches(label,#"(?i)^\s*(ok|yes|continue|allow|accept|agree|complete|finish|grant)\s*$"#) }   // a map-free menu replay cannot prove a generic confirmation is safe
        let context = ([map.window] + map.texts + map.nodes.filter { ["AXSheet","AXDialog"].contains($0.role) }.map(\.label)).joined(separator:" ")
        return matches(label,#"(?i)^\s*(ok|yes|continue|allow|accept|agree|complete|finish|grant)\s*$"#) && matches(context,riskyPattern)
    }
    static func secret(_ s: String) -> Bool { matches(s, secretPattern) }
    static func mask(_ s: String) -> String {
        var s = s.replacingOccurrences(of: #"\b(?:\d[ -]?){13,19}\b|\b\d{3}[- ]\d{2}[- ]\d{4}\b|\b\d{6,8}\b"#, with: "[SECRET]", options: .regularExpression)
        if matches(s, #"(?i)(one.?time|verification|security|auth|otp|code)\D{0,20}\d{4,8}"#) {
            s = s.replacingOccurrences(of: #"\b\d{4,8}\b"#, with: "[SECRET]", options: .regularExpression)
        }
        return s
    }
    static func digest(_ parts: [String], maskDigits: Bool = false) -> String {
        let s = parts.joined(separator: "\n"), text = maskDigits ? s.replacingOccurrences(of: #"\d"#, with: "#", options: .regularExpression) : s
        // Stable across helper processes (Swift's Hasher is deliberately randomized).
        return String(text.utf8.reduce(UInt64(14695981039346656037)) { ($0 ^ UInt64($1)) &* 1099511628211 }, radix: 16)
    }
    static func normalized(_ s: String) -> String { s.lowercased().split(whereSeparator: \.isWhitespace).joined(separator: " ").replacingOccurrences(of: "…", with: "...").replacingOccurrences(of: "[\u{2010}-\u{2015}\u{2212}]", with: "-", options: .regularExpression) }   // macOS writes "Wi‑Fi" with a non-breaking hyphen
    static func rank(_ label: String, _ text: String) -> Int {
        let l = normalized(label), t = normalized(text)
        guard !t.isEmpty else { return 0 }
        if l == t { return 4 }; if l.hasPrefix(t) { return 3 }
        if matches(l, #"\b"# + NSRegularExpression.escapedPattern(for: t) + #"\b"#) { return 2 }
        return l.contains(t) ? 1 : 0
    }
    static func keys(_ text: String) throws -> (CGKeyCode, CGEventFlags) {
        let input = normalized(text).replacingOccurrences(of:" ",with:"")
        var parts = (input.hasSuffix("++") ? String(input.dropLast()) + "=" : input).split(separator: "+").map(String.init), flags: CGEventFlags = []
        guard let key = parts.popLast(), !key.isEmpty else { throw Failure("Unknown key.") }
        for part in parts {
            switch part {
            case "cmd", "command", "⌘": flags.insert(.maskCommand)
            case "shift", "⇧": flags.insert(.maskShift)
            case "ctrl", "control", "⌃": flags.insert(.maskControl)
            case "alt", "option", "opt", "⌥": flags.insert(.maskAlternate)
            default: throw Failure("Unknown modifier: \(part)")
            }
        }
        let names: [String: CGKeyCode] = ["return":36,"enter":36,"esc":53,"escape":53,"tab":48,"space":49,"delete":51,"backspace":51,"forwarddelete":117,"pagedown":121,"pageup":116,"home":115,"end":119,"left":123,"right":124,"down":125,"up":126,
            "a":0,"s":1,"d":2,"f":3,"h":4,"g":5,"z":6,"x":7,"c":8,"v":9,"b":11,"q":12,"w":13,"e":14,"r":15,"y":16,"t":17,"1":18,"2":19,"3":20,"4":21,"6":22,"5":23,"=":24,"9":25,"7":26,"-":27,"8":28,"0":29,
            "]":30,"o":31,"u":32,"[":33,"i":34,"p":35,"l":37,"j":38,"'":39,"k":40,";":41,"\\":42,",":43,"/":44,"n":45,"m":46,".":47,"`":50,"f1":122,"f2":120,"f3":99,"f4":118,"f5":96,"f6":97,"f7":98,"f8":100,"f9":101,"f10":109,"f11":103,"f12":111]
        guard let code = names[["plus":"=","zoomin":"=","minus":"-","zoomout":"-" ][key] ?? key] else { throw Failure("Unknown key: \(key)") }
        return (code, flags)
    }
    static func riskyKey(_ text: String) throws -> Bool {
        let (code, flags) = try keys(text)
        return (flags.contains(.maskCommand) && [12,13,36,51,117].contains(code)) || (flags.contains([.maskCommand,.maskShift]) && code == 2) || (flags.contains([.maskCommand,.maskAlternate]) && code == 53)
    }
    static func attribute(_ e: AXUIElement, _ name: String) -> CFTypeRef? { axAttribute(e, name) }
    static func element(_ e: AXUIElement, _ name: String) -> AXUIElement? {
        guard let v = attribute(e, name), CFGetTypeID(v) == AXUIElementGetTypeID() else { return nil }; return (v as! AXUIElement)
    }
    static func children(_ e: AXUIElement) -> [AXUIElement] { Array(((attribute(e, kAXChildrenAttribute) as? [AXUIElement]) ?? []).prefix(400)) }
    static func frame(_ e: AXUIElement) -> CGRect {
        var p = CGPoint.zero, s = CGSize.zero
        if let v = attribute(e, kAXPositionAttribute), CFGetTypeID(v) == AXValueGetTypeID() { AXValueGetValue(v as! AXValue, .cgPoint, &p) }
        if let v = attribute(e, kAXSizeAttribute), CFGetTypeID(v) == AXValueGetTypeID() { AXValueGetValue(v as! AXValue, .cgSize, &s) }
        return CGRect(origin: p, size: s)
    }
    static func array(_ r: CGRect) -> [Double] { [r.minX, r.minY, r.width, r.height] }
    static func name(_ e: AXUIElement) -> String {
        func direct(_ item: AXUIElement) -> String {
            for key in [kAXTitleAttribute, kAXDescriptionAttribute, "AXLabel", kAXHelpAttribute, "AXPlaceholderValue"] {
                if let s = attribute(item, key) as? String, !s.isEmpty { return String(mask(s).prefix(160)) }
            }
            let role = attribute(item, kAXRoleAttribute) as? String ?? ""
            return ["AXStaticText", "AXHeading"].contains(role) ? String(mask(attribute(item, kAXValueAttribute) as? String ?? "").prefix(160)) : ""
        }
        let own = direct(e), role = attribute(e, kAXRoleAttribute) as? String ?? ""
        if !own.isEmpty && ![normalized(role),normalized(role.replacingOccurrences(of:"AX",with:""))].contains(normalized(own)) { return own }
        guard ["AXRow","AXCell","AXButton","AXCheckBox","AXSwitch","AXRadioButton","AXPopUpButton","AXDisclosureTriangle"].contains(role) else { return "" }
        var queue = children(e), cursor = 0, parts: [String] = []
        if let title = element(e,kAXTitleUIElementAttribute) {
            let text = direct(title)
            if !text.isEmpty { parts.append(text) }
        }
        while cursor < queue.count && cursor < 24 && parts.joined(separator:" ").count < 160 {
            let child = queue[cursor]; cursor += 1
            let text = direct(child)
            if !text.isEmpty && !parts.contains(text) { parts.append(text) }
            queue += children(child)
        }
        if parts.isEmpty, let parent = element(e,kAXParentAttribute) {
            var nearby = children(parent), i = 0
            while i < nearby.count && i < 24 && parts.joined(separator:" ").count < 160 {
                let item = nearby[i]; i += 1
                if !CFEqual(item,e) {
                    let text = direct(item)
                    if !text.isEmpty && !parts.contains(text) { parts.append(text) }
                }
                nearby += children(item)
            }
        }
        return String(parts.joined(separator:" ").prefix(160))
    }
    static func trusted() throws { guard AXIsProcessTrusted() else { throw Failure("Allow Rabik in System Settings → Privacy & Security → Accessibility") }; AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(),0.15) }
    static func app(_ request: String? = nil) throws -> NSRunningApplication {
        if let request, !request.isEmpty {
            if let pid = Int32(request), let a = NSRunningApplication(processIdentifier: pid) { MiniScreen.work(a); return a }
            let apps = NSWorkspace.shared.runningApplications.filter { normalized($0.localizedName ?? "") == normalized(request) || $0.bundleIdentifier == request }
            guard apps.count == 1 else { throw Failure("No unique running app named \(request).") }; MiniScreen.work(apps[0]); return apps[0]
        }
        guard let a = NSWorkspace.shared.frontmostApplication else { throw Failure("No front app.") }; return a
    }
    static func windowElement(_ e: AXUIElement, app: AXUIElement) -> Bool {
        !CFEqual(e,app) && ["AXWindow","AXSheet"].contains(attribute(e,kAXRoleAttribute) as? String ?? "")
    }
    // The window's Core Graphics number: its AX number, else the one window of this app with exactly its frame; "" when unknown.
    static func windowNumber(_ a: NSRunningApplication, _ w: AXUIElement) -> String {
        if let number = axWindowNumber(w) { return number.stringValue }
        let wf = frame(w)
        let windows = (CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? []).filter {
            ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == a.processIdentifier && ($0[kCGWindowLayer as String] as? Int) == 0 &&
            ($0[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation:$0) }.map { abs($0.minX - wf.minX) < 2 && abs($0.minY - wf.minY) < 2 && abs($0.width - wf.width) < 2 && abs($0.height - wf.height) < 2 } == true
        }
        return windows.count == 1 ? (windows[0][kCGWindowNumber as String] as? NSNumber)?.stringValue ?? "" : ""
    }
    static func userWindowLists() -> [String: [String]] {
        userWindowsFile.flatMap { try? Data(contentsOf: $0) }.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: [String]] } ?? [:]
    }
    static func keepTaskWindow(_ a: NSRunningApplication, _ w: AXUIElement, _ lists: [String: [String]]) {
        let own = windowNumber(a,w), key = String(a.processIdentifier)
        guard claims, let file = userWindowsFile, lists[key] == nil, !own.isEmpty else { return }
        let others = (CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? []).compactMap {
            ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == a.processIdentifier && ($0[kCGWindowLayer as String] as? Int) == 0 ? ($0[kCGWindowNumber as String] as? NSNumber)?.stringValue : nil
        }
        try? JSONSerialization.data(withJSONObject: lists.merging([key: others.filter { $0 != own }]) { $1 }).write(to: file, options: .atomic)
    }
    static func root(_ a: NSRunningApplication) throws -> (AXUIElement, AXUIElement) {
        try checkStopped()
        guard !a.isTerminated else { throw Failure("The mapped app closed. Run see again.") }
        let e = AXUIElementCreateApplication(a.processIdentifier), start = Date()
        // Unsupported AX attributes are harmless; request lazy accessibility in any app.
        _ = AXUIElementSetAttributeValue(e, "AXManualAccessibility" as CFString, kCFBooleanTrue)
        let enhancedKey = "AXEnhancedUserInterface", oldEnhanced = attribute(e,enhancedKey)
        let changedEnhanced = oldEnhanced.map { !CFEqual($0,kCFBooleanTrue) } ?? false
        if changedEnhanced, let oldEnhanced,
           AXUIElementSetAttributeValue(e,enhancedKey as CFString,kCFBooleanTrue) == .success {
            // Keep lazy AX content available through traversal and action verification.
            accessibilityRestores.append { _ = AXUIElementSetAttributeValue(e,enhancedKey as CFString,oldEnhanced) }
        }
        let axWindows = (attribute(e,kAXWindowsAttribute) as? [AXUIElement]) ?? []
        // A pinned task window resolves exactly or fails: never a stand-in, such as the user's own window of the same app.
        // It is found the same ways as an unpinned one (an app's AX window list can omit its focused window).
        let all = [element(e,kAXFocusedWindowAttribute), element(e,kAXMainWindowAttribute)].compactMap { $0 } + axWindows
        let lists = userWindowLists(), users = Set(lists[String(a.processIdentifier)] ?? [])
        func allowed(_ w: AXUIElement) -> Bool { (pinnedWindow.map { windowNumber(a,w) == $0 } ?? true) && (users.isEmpty || !users.contains(windowNumber(a,w))) }
        if let aim, let n = windowAt(aim, a.processIdentifier).map(String.init), let w = all.first(where: { windowNumber(a,$0) == n }), windowElement(w,app:e) {
            guard allowed(w) else { throw Failure("That point is in the user's other \(a.localizedName ?? "app") window, not this task's. Nothing was done; say so; do not switch windows.") }
            keepTaskWindow(a,w,lists); return (e,w)
        }
        for w in all.filter(allowed) {
            try checkStopped(); if Date().timeIntervalSince(start) >= 0.3 { break }
            if windowElement(w,app:e) { keepTaskWindow(a,w,lists); return (e,w) }
        }
        // Some apps omit AXWindows. Hit-test only this app's own CG window frames.
        let windows = (CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]]) ?? []
        for info in windows where (info[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == a.processIdentifier && (info[kCGWindowLayer as String] as? Int).map({ (0..<20).contains($0) || $0 == 101 }) == true {   // 101: pop-up menu level, where menu bar panels (Bluetooth, Wi-Fi) open; a pin is checked on the window found
            if Date().timeIntervalSince(start) >= 0.3 { break }
            guard let bounds = info[kCGWindowBounds as String] as? NSDictionary, let rect = CGRect(dictionaryRepresentation:bounds) else { continue }
            var hit: AXUIElement?
            AXUIElementCopyElementAtPosition(e,Float(rect.midX),Float(rect.midY),&hit)
            if hit == nil || hit.map({ CFEqual($0,e) }) == true { AXUIElementCopyElementAtPosition(AXUIElementCreateSystemWide(),Float(rect.midX),Float(rect.midY),&hit) }
            if let hit { var pid:pid_t = 0; AXUIElementGetPid(hit,&pid); if pid != a.processIdentifier { continue } }
            if var current = hit {
                for _ in 0..<40 {
                    try checkStopped(); if Date().timeIntervalSince(start) >= 0.3 { break }
                    if windowElement(current,app:e) { var pid:pid_t = 0; AXUIElementGetPid(current,&pid); if pid == a.processIdentifier && allowed(current) { keepTaskWindow(a,current,lists); return (e,current) } }
                    guard let parent = element(current,kAXParentAttribute), !CFEqual(parent,current) else { break }; current = parent
                }
            }
        }
        if pinnedWindow != nil { throw Failure("This task's \(a.localizedName ?? "app") window closed or changed. Nothing was done; run see again.") }
        if !users.isEmpty { throw Failure("This task's \(a.localizedName ?? "app") window closed. Nothing was done; the other \(a.localizedName ?? "app") windows are the user's, not this task's. Say so; do not switch windows.") }
        // Menu-bar-only apps (Control Center, Wi-Fi, third-party icons at the top right): map their status items instead.
        if let extras = element(e, "AXExtrasMenuBar") { return (e, extras) }
        throw Failure("No accessible window in \(a.localizedName ?? "app").")
    }
    // Read document content independently of the small, visible action map.
    static func documentIdentity(_ a: NSRunningApplication, _ w: AXUIElement) -> String {
        if let number = axWindowNumber(w)?.intValue, number != 0 { return "\(a.processIdentifier):\(number)" }
        let title = normalized(name(w)).replacingOccurrences(of: #"\s+[-–—]\s+[^-–—]+$"#, with:"", options:.regularExpression)
        return "\(a.processIdentifier):0:\(title)"
    }
    static func identify(_ a: NSRunningApplication) throws -> [String: Any] {
        let (_, w) = try root(a)
        return ["identity": documentIdentity(a,w), "app": a.localizedName ?? "app", "window": mask(name(w))]
    }
    static func read(_ a: NSRunningApplication, more: Bool = false, head: Bool = false) throws -> [String: Any] {
        let (_, w) = try root(a)
        let file = state.deletingLastPathComponent().appendingPathComponent("document-read.json")
        let identity = documentIdentity(a,w)
        func resolvePath(_ path: [Int]) throws -> AXUIElement {
            var item = w
            for index in path {
                let children = attribute(item, kAXChildrenAttribute) as? [AXUIElement] ?? []
                guard children.indices.contains(index) else { throw Failure("The document changed. Read again at offset 0.") }
                item = children[index]
            }
            return item
        }
        func signature(_ item: AXUIElement) -> String {
            let role = attribute(item, kAXRoleAttribute) as? String ?? "", label = name(item)
            let hidden = role == "AXSecureTextField" || attribute(item, kAXSubroleAttribute) as? String == "AXSecureTextField" || (["AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"].contains(role) && secret(label))
            let value = hidden ? "" : String(describing: attribute(item, kAXValueAttribute) ?? "" as CFString)
            return digest([role, label, value, String((attribute(item, kAXChildrenAttribute) as? [AXUIElement])?.count ?? 0)])
        }
        var paths: [[Int]] = [[]], guards: [[String: Any]] = [], seen = Set<AXUIElement>()
        if more {
            guard let data = try? Data(contentsOf: file), let saved = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  saved["identity"] as? String == identity, let pending = saved["paths"] as? [[Int]] else { throw Failure("The document changed. Read again at offset 0.") }
            guards = saved["guards"] as? [[String: Any]] ?? []
            for check in guards {
                guard let path = check["path"] as? [Int] else { throw Failure("Read again at offset 0.") }
                let item = try resolvePath(path)
                guard check["signature"] as? String == signature(item) else { throw Failure("The document changed. Read again at offset 0.") }
                seen.insert(item)
            }
            paths = pending
        }
        func orderedPaths(_ item: AXUIElement, _ path: [Int]) -> [[Int]] {
            let items = attribute(item, kAXChildrenAttribute) as? [AXUIElement] ?? []
            let ranked = items.indices.map { index -> (Int,Int,Double) in
                let child = items[index]
                let role = attribute(child,kAXRoleAttribute) as? String ?? "", area = frame(child).width * frame(child).height
                let rank = ["AXTextArea","AXWebArea","AXDocument","AXScrollArea","AXTable","AXOutline"].contains(role) ? 0 :
                           ["AXToolbar","AXMenuBar","AXMenu"].contains(role) ? 2 : 1
                return (index,rank,area)
            }
            return ranked.sorted { $0.1 == $1.1 ? $0.2 > $1.2 : $0.1 < $1.1 }.map { path + [$0.0] }
        }
        let start = Date(), limit = head ? 1500 : 16000, seconds = head ? 0.32 : 5.0
        var cursor = 0, texts: [String] = [], size = 0, page = "", hasWeb = false
        while cursor < paths.count && size < limit && Date().timeIntervalSince(start) < seconds {
            try checkStopped()
            let path = paths[cursor]; cursor += 1
            let item = try resolvePath(path)
            if !seen.insert(item).inserted { continue }
            if !head { guards.append(["path": path, "signature": signature(item)]) }
            let role = attribute(item, kAXRoleAttribute) as? String ?? ""
            let label = [kAXTitleAttribute, kAXDescriptionAttribute, "AXLabel", kAXHelpAttribute, "AXPlaceholderValue"].compactMap { attribute(item, $0) as? String }.first(where: { !$0.isEmpty }) ?? ""
            if role == "AXSecureTextField" || attribute(item, kAXSubroleAttribute) as? String == "AXSecureTextField" ||
               (["AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"].contains(role) && secret(name(item))) ||
               (["AXStaticText", "AXHeading"].contains(role) && secret(name(item))) { continue }
            let raw = attribute(item, kAXValueAttribute)
            let value = raw as? String ?? (raw as? NSAttributedString)?.string ?? (raw as? NSNumber)?.stringValue ?? ""
            func append(_ text: String) {
                guard !text.isEmpty, mask(text) == text else { return }
                let clipped = head ? String(text.prefix(max(0,limit - size))) : text
                if !clipped.isEmpty { texts.append(clipped); size += clipped.count }
            }
            append(label)
            if value != label { append(value) }
            if role == "AXWebArea" {
                hasWeb = true
                if let url = attribute(item, "AXURL") {
                    page = mask((url as? URL)?.absoluteString ?? (url as? String ?? String(describing:url)))
                    append(page)
                }
            }
            if value.isEmpty || !["AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"].contains(role) {
                paths.insert(contentsOf:orderedPaths(item,path),at:cursor)
            }
        }
        if !head {
            let boundedGuards = guards.count <= 64 ? guards : [guards[0]] + guards.suffix(63)
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONSerialization.data(withJSONObject: ["identity": identity, "paths": Array(paths.dropFirst(cursor)), "guards": boundedGuards]).write(to: file, options: .atomic)
            chmod(file.path, 0o600)
        }
        return ["text": texts.joined(separator: "\n"), "incomplete": cursor < paths.count, "identity": identity, "page": page, "web": hasWeb,
                "app": a.localizedName ?? "app", "window": mask(name(w))]
    }
    static func capture(_ a: NSRunningApplication, offscreen: Bool = false) throws -> Map {
        let (e, w) = try root(a), wf = frame(w), start = Date()
        var m = Map(pid: a.processIdentifier, app: a.localizedName ?? "app", window: name(w), windowFrame: array(wf), nodes: [], texts: [], page: "", focused: "", scroll: [])
        m.windowID = windowNumber(a,w)
        var queue: [(AXUIElement, [Int], CGRect)] = [], visited: [AXUIElement] = []
        queue.append((w, [], wf))
        // Keep menus available, but inspect the window's content before global chrome uses the native-app budget.
        if let menu = element(e, kAXMenuBarAttribute) { queue.append((menu, [-1], .null)) }
        for (i, child) in children(e).enumerated() where attribute(child, kAXRoleAttribute) as? String == "AXMenu" { queue.append((child, [-2, i], .null)) }
        let focused = element(e, kAXFocusedUIElementAttribute)
        var cursor = 0, later: [(AXUIElement, [Int], CGRect)] = [], deferring = true
        while true {
            // Web pages last: their links would use up the budget before an app's own toolbar (Chrome's Extensions button). --web reads pages.
            if cursor == queue.count, deferring { deferring = false; queue += later }
            guard cursor < queue.count && cursor < (offscreen ? 6000 : 1800) && Date().timeIntervalSince(start) < 1 else { break }
            try checkStopped()
            let (item, path, clip) = queue[cursor]; cursor += 1
            if visited.contains(where: { CFEqual($0, item) }) { continue }; visited.append(item)
            let role = attribute(item, kAXRoleAttribute) as? String ?? "", bounds = frame(item)
            let visible = clip.isNull ? bounds : bounds.intersection(clip)
            let menu = role.contains("Menu"), shown = offscreen || menu || bounds.isEmpty || (!visible.isNull && visible.width >= 4 && visible.height >= 4)
            if !shown { continue }
            let label = name(item), hidden = role == "AXSecureTextField" || attribute(item, kAXSubroleAttribute) as? String == "AXSecureTextField" || secret(label)
            var value = ""
            if !hidden, let raw = attribute(item, kAXValueAttribute) {
                value = String(mask(raw as? String ?? (raw as? NSNumber)?.stringValue ?? "").prefix(400))
            }
            if role == "AXWebArea", let url = attribute(item, "AXURL") { let s = (url as? URL)?.absoluteString ?? (url as? String ?? ""); if s.hasPrefix("http") { m.page = mask(s) } }
            if role == "AXWebArea", deferring { later.append((item, path, clip)); visited.removeLast(); continue }
            if let focused, CFEqual(focused, item) { m.focused = mask(label.isEmpty ? role : label); m.focusIdentity = "\(role):\(path):\(array(bounds))" }
            if role == "AXScrollArea", let bar = element(item, kAXVerticalScrollBarAttribute), let n = attribute(bar, kAXValueAttribute) as? NSNumber { m.scroll.append(n.doubleValue) }
            if ["AXStaticText", "AXHeading"].contains(role) {
                let text = mask(label.isEmpty ? value : label)
                if !text.isEmpty && !m.texts.contains(text) && m.texts.count < 40 { m.texts.append(text) }
            } else if !["AXApplication","AXWindow","AXGroup","AXScrollArea","AXWebArea","AXUnknown","AXImage","AXMenuBar","AXMenu"].contains(role), !(role.isEmpty && label.isEmpty), m.nodes.count < 70, !bounds.isEmpty || menu {   // a background app's menus have no frame but still open by path
                let r = menu || offscreen ? bounds : visible
                if !m.nodes.contains(where: { $0.role == role && $0.label == mask(label) && $0.frame == array(r) }) {
                    m.nodes.append(Node(id: m.nodes.count + 1, role: role, label: mask(label.isEmpty ? role : label), value: value, frame: array(r), path: path, secret: hidden))
                }
            }
            var childClip = clip
            if !offscreen && ["AXWindow","AXSheet","AXScrollArea","AXWebArea"].contains(role), !bounds.isEmpty { childClip = clip.isNull ? bounds : clip.intersection(bounds) }
            if ["AXTextField","AXTextArea","AXSecureTextField","AXSearchField","AXComboBox"].contains(role) { continue }
            if role == "AXMenuBarItem", (attribute(item, kAXSelectedAttribute) as? Bool) != true { continue }
            let ordered = children(item).enumerated().sorted {
                let priority = { (child: AXUIElement) in
                    let r = attribute(child,kAXRoleAttribute) as? String ?? ""
                    return ["AXSplitGroup","AXOutline","AXTable","AXScrollArea","AXSheet"].contains(r) ? 0 :
                           ["AXToolbar","AXMenuBar","AXMenu"].contains(r) ? 2 : 1
                }
                return priority($0.element) < priority($1.element)
            }
            for (i, child) in ordered { queue.append((child, path + [i], childClip)) }
        }
        return m
    }
    static func save(_ map: Map) throws {
        try FileManager.default.createDirectory(at: state.deletingLastPathComponent(), withIntermediateDirectories: true)
        var stored = try JSONSerialization.jsonObject(with: JSONEncoder().encode(map)) as! [String:Any]
        stored["signature"] = map.signature; stored["rich"] = map.rich
        try JSONSerialization.data(withJSONObject:stored).write(to: state, options: .atomic)
        chmod(state.path, 0o600)
    }
    static func load() throws -> Map {
        guard let data = try? Data(contentsOf: state), let m = try? JSONDecoder().decode(Map.self, from: data) else { throw Failure("Run see first.") }; return m
    }
    static func at(_ path: [Int], _ a: NSRunningApplication) throws -> AXUIElement {
        let (e, w) = try root(a); var current = w, path = path
        if path.first == -1 { guard let menu = element(e, kAXMenuBarAttribute) else { throw Failure("Menu unavailable.") }; current = menu; path.removeFirst() }
        else if path.first == -2 { path.removeFirst(); current = e }
        for i in path { let c = children(current); guard c.indices.contains(i) else { throw Failure("The screen changed. Run see again.") }; current = c[i] }
        return current
    }
    static func drawAnchor(_ label: String, state: String) throws -> (CGRect,AXUIElement?,DrawingWindow) {
        let old = try JSONDecoder().decode(Map.self,from:Data(contentsOf:URL(fileURLWithPath:state)))
        let a = try app(String(old.pid)), fresh = try capture(a)
        guard fresh.windowID == old.windowID, fresh.windowFrame == old.windowFrame else { throw Failure("The window moved. Read again.") }
        let e: AXUIElement?
        if let id = Int(label) {
            guard let oldNode = old.nodes.first(where: { $0.id == id }),
                  let node = fresh.nodes.first(where: { $0.path == oldNode.path }), node.role == oldNode.role, node.label == oldNode.label else { throw Failure("The control changed. Read again.") }
            e = try at(node.path,a)   // a guided value change must not invalidate stable control identities
        } else { e = try resolve(label,map:fresh,a:a).1 }
        guard let e else { throw Failure("No accessible drawing target.") }
        guard let id = UInt32(fresh.windowID),
              let info = (CGWindowListCopyWindowInfo(.optionIncludingWindow,id) as? [[String:Any]])?.first,
              let bounds = MiniScreen.bounds(info) else { throw Failure("The window closed. Read again.") }
        return (visibleFrame(e),e,DrawingWindow(pid:fresh.pid,windowID:fresh.windowID,windowFrame:array(bounds)))
    }
    static func point(_ text: String) throws -> CGPoint? {
        guard matches(text,#"^\s*(?:\d+:)?-?[\d.]+\s*,\s*-?[\d.]+\s*$"#) else { return nil }
        let pieces = text.split(separator: ":", omittingEmptySubsequences: false), pair = pieces.last!.split(separator: ",", omittingEmptySubsequences: false)
        guard pair.count == 2 else { return nil }
        guard let x = Double(pair[0]), let y = Double(pair[1]), x.isFinite, y.isFinite else { throw Failure("Invalid coordinates.") }
        if pieces.count == 1 { return CGPoint(x: x, y: y) }
        guard pieces.count == 2, let n = Int(pieces[0]), NSScreen.screens.indices.contains(n - 1) else { throw Failure("No such screen.") }
        let screen = NSScreen.screens[n - 1], id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID(), r = CGDisplayBounds(id)
        guard x >= 0, y >= 0, x <= 1280, y <= r.height / (r.width / 1280) else { throw Failure("Point is outside that picture.") }
        return picturePoint(x, y, in: r)
    }
    // A --look picture spot (1280 px wide, from this display's top-left) to a global display point; Quartz events use display points.
    static func picturePoint(_ x: Double, _ y: Double, in r: CGRect) -> CGPoint {
        let scale = r.width / 1280
        return CGPoint(x: r.minX + x * scale, y: r.minY + y * scale)
    }
    static func visibleFrame(_ e: AXUIElement) -> CGRect {
        var visible = frame(e), current = e
        for _ in 0..<40 {
            guard let parent = element(current,kAXParentAttribute) else { break }
            let role = attribute(parent,kAXRoleAttribute) as? String ?? ""
            if ["AXWindow","AXScrollArea","AXWebArea","AXSheet"].contains(role), !frame(parent).isEmpty { visible = visible.intersection(frame(parent)) }
            current = parent
        }
        return visible
    }
    static func resolve(_ text: String, map: Map, a: NSRunningApplication, near: String = "") throws -> (Node, AXUIElement?) {
        if let id = Int(text) {
            guard let n = map.nodes.first(where: { $0.id == id }) else { throw Failure("No such control. Run see again.") }; return (n, try at(n.path, a))
        }
        if let p = try point(text) {
            if let n = map.nodes.filter({ CGRect(x:$0.frame[0],y:$0.frame[1],width:$0.frame[2],height:$0.frame[3]).contains(p) }).min(by: { $0.frame[2] * $0.frame[3] < $1.frame[2] * $1.frame[3] }) { return (n, try at(n.path,a)) }
            let (e, _) = try root(a); var hit: AXUIElement?
            AXUIElementCopyElementAtPosition(e, Float(p.x), Float(p.y), &hit)
            if let hit { var pid: pid_t = 0; AXUIElementGetPid(hit, &pid); guard pid == a.processIdentifier else { throw Failure("That point belongs to another app. Run see again.") } }
            if var current = hit {
                for _ in 0..<5 {
                    let role = attribute(current, kAXRoleAttribute) as? String ?? ""
                    if !name(current).isEmpty && !["AXStaticText","AXGroup","AXWindow","AXApplication","AXScrollArea","AXWebArea"].contains(role) {
                        let n = Node(id: 0, role: role, label: mask(name(current)), value: "", frame: [p.x,p.y,0,0], path: [], secret: secret(name(current)))
                        return (n, current)
                    }
                    guard let parent = element(current, kAXParentAttribute) else { break }; current = parent
                }
            }
            let bounds = CGRect(x:map.windowFrame[0],y:map.windowFrame[1],width:map.windowFrame[2],height:map.windowFrame[3])
            guard bounds.contains(p) else { throw Failure("That point is outside the mapped window. Run see again.") }
            return (Node(id:0,role:"AXUnknown",label:"Unidentified screen point \(Int(p.x)),\(Int(p.y))",value:"",frame:[p.x,p.y,0,0],path:[],secret:false),nil)
        }
        let candidates = map.nodes.filter { rank($0.label, text) > 0 }
        var anchor = map.nodes.first { rank($0.label, near) == 4 }
        if anchor == nil, !near.isEmpty, let e = try findText(near,a), rank(name(e),near) == 4 {
            let bounds = visibleFrame(e)
            if !bounds.isNull && bounds.width >= 4 && bounds.height >= 4 { anchor = Node(id:0,role:"AXStaticText",label:near,value:"",frame:array(bounds),path:[],secret:false) }
        }
        func distance(_ n: Node) -> Double { guard let anchor else { return Double(n.id) }; return hypot(n.spot.x - anchor.spot.x, n.spot.y - anchor.spot.y) }
        let sorted = candidates.sorted { rank($0.label, text) == rank($1.label, text) ? distance($0) < distance($1) : rank($0.label, text) > rank($1.label, text) }
        if near.isEmpty && (sorted.first.map { rank($0.label,text) } ?? 0) < 4, let e = try findText(text,a), rank(name(e),text) > (sorted.first.map { rank($0.label,text) } ?? 0) {
            let r = visibleFrame(e)
            if !r.isNull && r.width >= 4 && r.height >= 4 {
                return (Node(id:0,role:attribute(e,kAXRoleAttribute) as? String ?? "AXStaticText",label:mask(name(e)),value:"",frame:array(r),path:[],secret:false),e)
            }
        }
        guard let n = sorted.first else { throw Failure("No visible control named \(quote(mask(text))). Use scroll-to for offscreen text.") }
        if near.isEmpty && sorted.count > 1 && rank(sorted[1].label, text) == rank(n.label, text) {
            let tied = sorted.prefix { rank($0.label, text) == rank(n.label, text) }
            if let row = tied.first(where: { $0.role == "AXRow" }),
               tied.allSatisfy({ $0.id == row.id || ($0.role == "AXCell" && $0.path.starts(with: row.path)) }) {
                return (row, try at(row.path, a))
            }
            throw Failure("More than one control named \(quote(text)); use near.")
        }
        if !near.isEmpty && anchor == nil { throw Failure("No nearby anchor named \(quote(near)).") }
        return (n, try at(n.path, a))
    }
    static func actions(_ e: AXUIElement) -> [String] { var names: CFArray?; AXUIElementCopyActionNames(e, &names); return names as? [String] ?? [] }
    static func perform(_ e: AXUIElement, _ names: [String]) -> Bool {
        let supported = actions(e)
        // cannotComplete: the press opened a modal sheet and the app stopped answering AX; the action ran, so never retry it with the mouse
        return names.contains { supported.contains($0) && [.success, .cannotComplete].contains(AXUIElementPerformAction(e, $0 as CFString)) }
    }
    static func menuItem(_ text: String, _ parent: AXUIElement) throws -> AXUIElement {
        var q = children(parent), i = 0
        while i < q.count && i < 300 {
            let e = q[i]; i += 1
            if rank(name(e), text) == 4 { return e }
            let role = attribute(e, kAXRoleAttribute) as? String ?? ""
            if role == "AXMenu" || role == "AXMenuBarItem" { q += children(e) }
        }
        throw Failure("No menu item named \(quote(text)).")
    }
    static func menu(_ path: String, _ a: NSRunningApplication, act: Bool) throws -> String {
        try checkStopped(); guard !a.isTerminated else { throw Failure("The target app closed.") }
        let e = AXUIElementCreateApplication(a.processIdentifier); AXUIElementSetMessagingTimeout(e,0.15)
        guard var parent = element(e, kAXMenuBarAttribute) else { throw Failure("No accessible menu bar.") }
        let parts = path.components(separatedBy: ">").map { $0.trimmingCharacters(in: .whitespaces) }
        guard parts.count > 1, parts.allSatisfy({ !$0.isEmpty }) else { throw Failure("Invalid menu path.") }
        var restore: (() -> Void)?, lease: Int32?
        if act {   // a press can bring the app forward: tell the focus guard it's on purpose, then put the user's app back
            try keysReachTask(a.processIdentifier)
            lease = try screenLease()
            DistributedNotificationCenter.default().postNotificationName(.init("rabik.raise"), object: nil, deliverImmediately: true)
            usleep(50_000); restore = restoreFocus(a)
        }
        defer { if let restore { usleep(30_000); restore() }; if let lease { flock(lease,LOCK_UN); Darwin.close(lease) } }
        for (index, part) in parts.enumerated() {
            try checkStopped()
            let item = try menuItem(part, parent), label = mask(name(item))
            if act { guard perform(item, ["AXPress","AXPick","AXOpen","AXShowMenu"]) else { throw Failure("Could not open menu \(quote(part)).") }; usleep(15_000) }
            parent = item
            // AX exposes AppKit submenus without opening them; no press occurs during safety resolution.
            if index == parts.count - 1 { return label }
        }
        throw Failure("Invalid menu path.")
    }
    // AXMenuItemCmdModifiers bits: 1 shift, 2 option, 4 control, 8 no command.
    static func isShortcut(_ text: String, cmdChar: String, modifiers: Int) -> Bool {
        guard let (_, flags) = try? keys(text), let key = normalized(text).replacingOccurrences(of:" ",with:"").split(separator:"+",omittingEmptySubsequences:false).last, key.count == 1 else { return false }
        return flags.contains(.maskCommand) && modifiers & 8 == 0 && cmdChar.uppercased() == key.uppercased() &&
            (modifiers & 1 != 0) == flags.contains(.maskShift) && (modifiers & 2 != 0) == flags.contains(.maskAlternate) && (modifiers & 4 != 0) == flags.contains(.maskControl)
    }
    // Background keys reach an app's views but never its menu shortcuts (a background cmd+s saves nothing; trycua/cua-driver found the same),
    // so a native app behind the user's runs the enabled menu item for that shortcut. Web content keeps its keys: the page may handle them.
    static func menuShortcut(_ text: String, _ a: NSRunningApplication) -> (AXUIElement, String)? {
        guard !MiniScreen.workInFront, NSWorkspace.shared.frontmostApplication?.processIdentifier != a.processIdentifier, !webFocused(a.processIdentifier) else { return nil }
        let application = AXUIElementCreateApplication(a.processIdentifier); AXUIElementSetMessagingTimeout(application, 0.15)
        guard let bar = element(application, kAXMenuBarAttribute) else { return nil }
        var queue = children(bar).dropFirst().map { ($0, [name($0)], 0) }, i = 0; let start = Date()   // the Apple menu belongs to the system
        while i < queue.count && i < 2000 && Date().timeIntervalSince(start) < 0.5 {
            let (item, path, depth) = queue[i]; i += 1
            if let char = attribute(item, "AXMenuItemCmdChar") as? String, !char.isEmpty {
                if isShortcut(text, cmdChar: char, modifiers: (attribute(item, "AXMenuItemCmdModifiers") as? NSNumber)?.intValue ?? 0),
                   attribute(item, kAXEnabledAttribute) as? Bool != false { return (item, mask(path.joined(separator: " > "))) }
            } else if depth < 6 {
                for child in children(item) { queue.append((child, attribute(child, kAXRoleAttribute) as? String == "AXMenu" ? path : path + [name(child)], depth + 1)) }
            }
        }
        return nil
    }
    static func sendKeys(_ text: String, pid: Int32, times: Int = 1) throws {
        let (code, flags) = try keys(text)
        guard (1...50).contains(times), let source = CGEventSource(stateID: .privateState) else { throw Failure("Invalid key repeat count.") }
        try keysReachTask(pid)
        let web = !flags.contains(.maskCommand) && NSWorkspace.shared.frontmostApplication?.processIdentifier != pid && webFocused(pid)
        for _ in 0..<times {
            try checkStopped()
            for down in [true, false] { guard let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: down) else { throw Failure("Could not create key event.") }; event.flags = flags; postKey(event, pid: pid, web: web) }
        }
    }
    // Background input: each event goes to the app's process with its window stamped in, so the pointer, the front app,
    // window order and Spaces stay as they are. The SkyLight calls are optional; without them the public per-process post is used.
    static let skyLight = dlopen("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight", RTLD_LAZY)
    static let stampLocation = dlsym(skyLight, "CGEventSetWindowLocation").map { unsafeBitCast($0, to: (@convention(c) (CGEvent, CGPoint) -> Void).self) }
    static let skyPost = dlsym(skyLight, "SLEventPostToPid").map { unsafeBitCast($0, to: (@convention(c) (pid_t, CGEvent) -> Void).self) }
    // Background web content (Chromium, Electron) takes keys as live input only through SkyLight with an authentication message
    // (macOS 15+; technique from trycua/cua-driver, MIT). Other keys keep the plain post: authenticated keys skip the path menu shortcuts use.
    static let authenticate = dlsym(skyLight, "SLEventSetAuthenticationMessage").map { unsafeBitCast($0, to: (@convention(c) (CGEvent, AnyObject) -> Void).self) }
    static func postKey(_ e: CGEvent, pid: Int32, web: Bool) {
        let factory = NSSelectorFromString("messageWithEventRecord:pid:version:")
        guard web, let skyPost, let authenticate, let type: AnyClass = NSClassFromString("SLSEventAuthenticationMessage"), (type as AnyObject).responds(to: factory),
              let method = (type as AnyObject).method(for: factory),
              let record = Unmanaged.passUnretained(e).toOpaque().load(fromByteOffset: 24, as: UnsafeMutableRawPointer?.self),   // CGEvent: CFRuntimeBase, UInt32, SLSEventRecord *
              let message = unsafeBitCast(method, to: (@convention(c) (AnyClass, Selector, UnsafeMutableRawPointer, Int32, UInt32) -> Unmanaged<AnyObject>?).self)(type, factory, record, pid, 0)?.takeUnretainedValue()
        else { return e.postToPid(pid) }
        authenticate(e, message); skyPost(pid, e)
    }
    // An app hands mouse input to a window's content only while it counts that window as key. This window-server focus record makes it so
    // without raising the window, activating the app or taking key from the user's window (yabai's focus without raise, via cua-driver).
    static let postRecord = dlsym(skyLight, "SLPSPostEventRecordTo").map { unsafeBitCast($0, to: (@convention(c) (UnsafeRawPointer, UnsafeRawPointer) -> Int32).self) }
    static let processForPid = dlsym(dlopen("/System/Library/Frameworks/ApplicationServices.framework/Frameworks/HIServices.framework/HIServices", RTLD_LAZY), "GetProcessForPID").map { unsafeBitCast($0, to: (@convention(c) (pid_t, UnsafeMutableRawPointer) -> Int32).self) }
    // Off (after the gesture) hands the app back its inactive state.
    static func focusWithoutRaise(_ pid: Int32, _ window: UInt32, on: Bool = true) {
        var psn: [UInt32] = [0, 0], record = [UInt8](repeating: 0, count: 0xF8)
        guard let postRecord, let processForPid, processForPid(pid, &psn) == 0 else { return }
        record[0x04] = 0xF8; record[0x08] = 0x0D; record[0x8A] = on ? 1 : 2
        withUnsafeBytes(of: window.littleEndian) { record.replaceSubrange(0x3C..<0x40, with: $0) }
        usleep(on ? 0 : 50_000)   // the gesture's queued events land while the window is still key
        _ = psn.withUnsafeBytes { p in record.withUnsafeBytes { postRecord(p.baseAddress!, $0.baseAddress!) } }
        usleep(on ? 50_000 : 0)   // AppKit settles its key window before the events arrive
    }
    // A click in a key window brings it in front of its app's other windows: the one that was in front goes back.
    static func keepOrder(_ pid: Int32) -> () -> Void {
        func top() -> UInt32? {
            ((CGWindowListCopyWindowInfo(.optionOnScreenOnly, kCGNullWindowID) as? [[String:Any]]) ?? []).first { ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid && ($0[kCGWindowLayer as String] as? Int) == 0 }
                .flatMap { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value }
        }
        let before = top()
        return {
            usleep(50_000)
            guard let before, top() != before, let a = NSRunningApplication(processIdentifier: pid),
                  let w = (attribute(AXUIElementCreateApplication(pid), kAXWindowsAttribute) as? [AXUIElement])?.first(where: { windowNumber(a, $0) == String(before) }) else { return }
            _ = perform(w, ["AXRaise"])
        }
    }
    static func deliver(_ e: CGEvent, at p: CGPoint, pid: Int32, window: UInt32, fields: [UInt32: Int64] = [:]) {
        e.flags = []; e.location = p; stampLocation?(e, p)
        let routing: [UInt32: Int64] = window == 0 ? [40: Int64(pid)] : [40: Int64(pid), 51: Int64(window), 91: Int64(window), 92: Int64(window)]
        for (field, value) in fields.merging(routing, uniquingKeysWith: { $1 }) { e.setIntegerValueField(CGEventField(rawValue: field)!, value: value) }
        if let skyPost { skyPost(pid, e) } else { e.postToPid(pid) }
    }
    static func targetWindow(_ a: NSRunningApplication) -> UInt32 { (try? root(a)).flatMap { UInt32(windowNumber(a,$0.1)) } ?? 0 }
    // The app's window a real click at p would reach: its topmost visible window there. A task's pinned window always wins.
    static func windowAt(_ p: CGPoint, _ pid: Int32) -> UInt32? {
        windowsAt(p).first { ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid }.flatMap { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value }
    }
    // Visible app windows (layer 0: never Rabik's own panels) containing p, front to back; none when a task window is pinned.
    static func windowsAt(_ p: CGPoint) -> [[String:Any]] {
        guard pinnedWindow == nil else { return [] }
        return ((CGWindowListCopyWindowInfo(.optionOnScreenOnly, kCGNullWindowID) as? [[String:Any]]) ?? []).filter {
            ($0[kCGWindowLayer as String] as? Int) == 0 && ($0[kCGWindowAlpha as String] as? Double ?? 1) > 0 &&
            ($0[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation:$0) }?.contains(p) == true
        }
    }
    // A click or drag at a screen point acts in the window a picture shows there, in any app; other targets use the mapped app.
    static func aimed(_ args: [String], _ old: Map) throws -> NSRunningApplication {
        aim = ["click","drag"].contains(args.first ?? "") && args.count > 1 ? try point(args[1]) : nil
        let owner = aim.flatMap { (windowsAt($0).first?[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value }
        return try app(String(owner ?? old.pid))
    }
    static func restoreFocus(_ a: NSRunningApplication) -> () -> Void {
        if MiniScreen.workInFront { return {} }
        let previous = NSWorkspace.shared.frontmostApplication
        let window = previous.flatMap { element(AXUIElementCreateApplication($0.processIdentifier),kAXFocusedWindowAttribute) }
        return {
            guard let previous, previous != a, !previous.isTerminated, NSWorkspace.shared.frontmostApplication == a else { return }
            previous.activate()
            if let window { _ = perform(window,["AXRaise"]) }
        }
    }
    static func webFocused(_ pid: Int32) -> Bool {
        let application = AXUIElementCreateApplication(pid); AXUIElementSetMessagingTimeout(application, 0.15)
        var item = element(application, kAXFocusedUIElementAttribute)
        for _ in 0..<64 {
            guard let e = item else { return false }
            if attribute(e, kAXRoleAttribute) as? String == "AXWebArea" { return true }
            item = element(e, kAXParentAttribute).flatMap { CFEqual($0, e) ? nil : $0 }
        }
        return false
    }
    // An app sends keys and menu commands to its own focused window. With a task window pinned, or user windows beside it, they go only when the task's window has the focus.
    static func keysReachTask(_ pid: Int32) throws {
        guard pinnedWindow != nil || userWindowLists()[String(pid)]?.isEmpty == false, let a = NSRunningApplication(processIdentifier: pid) else { return }
        let (e, w) = try root(a)
        func reaches() -> Bool {
            var current = element(e,kAXFocusedUIElementAttribute)
            if current.map({ CFEqual($0,e) }) ?? true { current = element(e,kAXFocusedWindowAttribute) }
            for _ in 0..<64 {
                guard let item = current else { return false }
                if CFEqual(item,w) { return true }
                current = element(item,kAXParentAttribute).flatMap { CFEqual($0,item) ? nil : $0 }
            }
            return false
        }
        if reaches() { return }
        if MiniScreen.workInFront { _ = perform(w,["AXRaise"]); usleep(50_000); if reaches() { return } }   // the user asked to work in front
        throw Failure("Keys would go to another \(a.localizedName ?? "app") window, not this task's. Nothing was pressed.")
    }
    static func mouse(_ from: CGPoint, _ a: NSRunningApplication, double: Bool = false, right: Bool = false, to: CGPoint? = nil, front: Bool = false) throws {
        guard env["RABIK_AX_ONLY"] != "1" else { throw Failure("Quartz mouse actions disabled for this fixture.") }
        let pid = a.processIdentifier, window = windowAt(from, a.processIdentifier) ?? targetWindow(a), gesture = Int64(DispatchTime.now().uptimeNanoseconds % 1_000_000_000)
        if front || window == 0 || MiniScreen.workInFront { return try frontMouse(from, a, double: double, right: right, to: to) }   // no known window: never an unbound event
        guard let source = CGEventSource(stateID: .hidSystemState) else { throw Failure("Could not create mouse event.") }
        // Field 0 carries the gesture phase, 1 the click count, 3 the button, 7 the subtype, 58 one id for the whole gesture.
        func post(_ type: CGEventType, _ p: CGPoint, phase: Int64, count: Int64, subtype: Int64 = 3, wait: UInt32) throws {
            let button: Int64 = [.rightMouseDown, .rightMouseUp, .rightMouseDragged].contains(type) ? 1 : 0
            guard let e = CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: p, mouseButton: button == 1 ? .right : .left) else { throw Failure("Could not create mouse event.") }
            deliver(e, at: p, pid: pid, window: window, fields: [0: phase, 1: count, 3: button, 7: subtype, 58: gesture]); usleep(wait * 1000)
        }
        let (down, dragged, up): (CGEventType, CGEventType, CGEventType) = right ? (.rightMouseDown, .rightMouseDragged, .rightMouseUp) : (.leftMouseDown, .leftMouseDragged, .leftMouseUp)
        try checkStopped()
        let restoreOrder = keepOrder(pid); defer { restoreOrder() }
        focusWithoutRaise(pid, window); defer { focusWithoutRaise(pid, window, on: false) }
        var held = false
        defer { if held { try? post(up, to ?? from, phase: 3, count: 1, wait: 0) } }
        // A move primes the window's hit-testing; an off-screen click opens Chromium's user-activation gate for background input.
        try post(.mouseMoved, from, phase: 2, count: 0, wait: 15)
        if !right { try post(.leftMouseDown, CGPoint(x: -1, y: -1), phase: 1, count: 1, wait: 1); try post(.leftMouseUp, CGPoint(x: -1, y: -1), phase: 2, count: 1, wait: 100) }
        if let to {
            try post(down, from, phase: 3, count: 1, subtype: 0, wait: 30); held = true
            for i in 1...20 { try checkStopped(); let t = Double(i) / 20; try post(dragged, CGPoint(x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t), phase: 3, count: 1, subtype: 0, wait: i == 20 ? 50 : 8) }
            try post(up, to, phase: 3, count: 1, subtype: 0, wait: 0); held = false
            return
        }
        for count in 1...(double ? 2 : 1) {
            try checkStopped()
            try post(down, from, phase: 3, count: Int64(count), wait: right ? 28 : 1); held = true
            try post(up, from, phase: 3, count: Int64(count), wait: double && count == 1 ? 80 : 0); held = false
        }
    }
    static func screenLease() throws -> Int32 { try lease("screen.lock") }
    static var leaseWaited = false
    // Locks shared by every Rabik process (the app and each hands helper): the screen, the clipboard, one app's input.
    static func lease(_ name: String, wait: Bool = true) throws -> Int32 {
        let root = (Prefs.path as NSString).deletingLastPathComponent
        let fd = Darwin.open(root + "/" + name, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw Failure("Could not lock \(name).") }
        let waiting = name == "screen.lock" ? env["RABIK_ASK"].map { $0 + "/screen-wait" } : nil
        defer { if let waiting { try? FileManager.default.removeItem(atPath: waiting) } }
        leaseWaited = false
        do {
            while flock(fd, LOCK_EX | LOCK_NB) != 0 {
                guard errno == EWOULDBLOCK, wait else { throw Failure("Could not lock \(name).") }
                leaseWaited = true
                if let waiting { try? Data().write(to: URL(fileURLWithPath: waiting), options: .atomic); try? FileManager.default.setAttributes([.posixPermissions:0o600], ofItemAtPath:waiting) }
                try checkStopped(); usleep(25_000)
            }
            return fd
        } catch { Darwin.close(fd); throw error }
    }
    static func unlock(_ fd: Int32) { flock(fd, LOCK_UN); Darwin.close(fd) }
    static func fingerprint(_ map: Map, around spot: CGPoint? = nil) -> [UInt8] {
        // No disk image is kept. With a spot: the real screen 64x40 points around it, minus Rabik's own ring and box, so a
        // click shows whether it took even when the target window is full screen or on another Space, where a window-only
        // capture returns a stale frame. Without a spot (scroll, settle): the target window's content, 64x40.
        final class Capture { let lock = NSLock(); var image: CGImage? }
        let result = Capture(), done = DispatchSemaphore(value: 0), id = spot.flatMap { windowAt($0, map.pid) } ?? UInt32(map.windowID)
        Task {
            defer { done.signal() }
            guard let all = try? await SCShareableContent.excludingDesktopWindows(true,onScreenWindowsOnly:false) else { return }
            let filter: SCContentFilter, cfg = SCStreamConfiguration(); cfg.width = 64; cfg.height = 40
            if let spot, let display = all.displays.first(where: { $0.frame.contains(spot) }) {
                filter = SCContentFilter(display: display, excludingWindows: all.windows.filter { $0.owningApplication?.bundleIdentifier == Bundle.main.bundleIdentifier })
                cfg.sourceRect = CGRect(x: spot.x - display.frame.minX - 32, y: spot.y - display.frame.minY - 20, width: 64, height: 40)
            } else {
                guard let window = all.windows.first(where: {
                          guard $0.owningApplication?.processID == map.pid && $0.windowLayer == 0 else { return false }
                          if let id { return $0.windowID == id }
                          return array($0.frame) == map.windowFrame
                      }) else { return }
                filter = SCContentFilter(desktopIndependentWindow: window)
            }
            guard let image = try? await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg) else { return }
            result.lock.withLock { result.image = image }
        }
        guard done.wait(timeout:.now() + 0.5) == .success else { return [] }
        result.lock.lock(); let captured = result.image; result.lock.unlock()
        guard let image = captured else { return [] }
        var pixels = [UInt8](repeating: 0, count: 64 * 40)
        pixels.withUnsafeMutableBytes { buffer in
            if let c = CGContext(data: buffer.baseAddress, width: 64, height: 40, bitsPerComponent: 8, bytesPerRow: 64, space: CGColorSpaceCreateDeviceGray(), bitmapInfo: 0) { c.interpolationQuality = .low; c.draw(image, in: CGRect(x: 0,y: 0,width: 64,height: 40)) }
        }
        return pixels
    }
    static func pixelsChanged(_ before: [UInt8], _ after: [UInt8], threshold: Double = 4) -> Bool {
        guard !before.isEmpty, before.count == after.count else { return false }
        return zip(before, after).reduce(0.0) { $0 + abs(Double($1.0) - Double($1.1)) } / Double(before.count) >= threshold
    }
    // The foreground route: the app comes forward and the real pointer acts, then the pointer and the user's app go back.
    // Used for work the user asked to see, a window without a known id, and a scroll nothing else could move.
    static func raise(_ a: NSRunningApplication) throws {
        DistributedNotificationCenter.default().postNotificationName(.init("rabik.raise"), object: nil, deliverImmediately: true)   // tell the focus guard this one is on purpose
        usleep(50_000)   // let the guard hear it before the app comes forward
        let (_, w) = try root(a); _ = perform(w, ["AXRaise"]); a.activate(); usleep(30_000)
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == a.processIdentifier else { throw Failure("Could not focus the mapped app.") }
    }
    static func frontMouse(_ from: CGPoint, _ a: NSRunningApplication, double: Bool, right: Bool, to: CGPoint?) throws {
        _ = NSApplication.shared   // the real pointer needs a window-server connection; the hands helper has none until now
        let lease = try screenLease(); defer { unlock(lease) }
        let restore = restoreFocus(a); defer { usleep(30_000); restore() }
        try raise(a)
        guard let source = CGEventSource(stateID: .privateState), let saved = CGEvent(source: source)?.location else { throw Failure("Could not create mouse event.") }
        let button: CGMouseButton = right ? .right : .left
        defer { CGWarpMouseCursorPosition(saved) }
        func post(_ type: CGEventType, _ p: CGPoint, _ count: Int) throws {
            guard let e = CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: p, mouseButton: button) else { throw Failure("Could not create mouse event.") }
            e.flags = []; e.setIntegerValueField(.mouseEventClickState, value: Int64(count)); e.post(tap: .cghidEventTap)
        }
        var held = false
        defer { if held { try? post(right ? .rightMouseUp : .leftMouseUp, to ?? from, 1) } }
        for count in 1...(double ? 2 : 1) {
            try checkStopped()
            try post(right ? .rightMouseDown : .leftMouseDown, from, count)
            held = true
            if let to {
                for i in 1...20 { try checkStopped(); let t = Double(i) / 20; try post(.leftMouseDragged, CGPoint(x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t), count); usleep(8_000) }
            }
            try post(right ? .rightMouseUp : .leftMouseUp, to ?? from, count)
            held = false
        }
    }
    static func frontWheel(_ direction: String, _ spot: CGPoint, _ a: NSRunningApplication, fraction: Double) throws {
        _ = NSApplication.shared   // the real pointer needs a window-server connection; the hands helper has none until now
        let lease = try screenLease(); defer { unlock(lease) }
        let restore = restoreFocus(a); defer { usleep(30_000); restore() }
        try raise(a)
        guard let source = CGEventSource(stateID: .privateState), let saved = CGEvent(source: source)?.location else { throw Failure("Could not create scroll event.") }
        defer { CGWarpMouseCursorPosition(saved) }; CGWarpMouseCursorPosition(spot)
        let vertical = ["down","up"].contains(direction), amount = Int32(((["down","right"].contains(direction) ? -500.0 : 500.0) * fraction).rounded())
        guard let event = CGEvent(scrollWheelEvent2Source: source, units: .pixel, wheelCount: 2, wheel1: vertical ? amount : 0, wheel2: vertical ? 0 : amount, wheel3: 0) else { throw Failure("Could not create scroll event.") }
        event.flags = []; event.post(tap: .cghidEventTap)
    }
    static func scrollArea(_ a: NSRunningApplication, target: CGPoint? = nil) throws -> AXUIElement {
        let (_, w) = try root(a), start = Date(); var queue = [w], i = 0, found: [AXUIElement] = []
        while i < queue.count && i < 1800 && Date().timeIntervalSince(start) < 0.3 {
            try checkStopped()
            let e = queue[i]; i += 1
            if attribute(e, kAXRoleAttribute) as? String == "AXScrollArea", target == nil || frame(e).contains(target!) { found.append(e) }
            queue += children(e)
        }
        guard let area = found.sorted(by: { target == nil ? frame($0).width * frame($0).height > frame($1).width * frame($1).height : frame($0).width * frame($0).height < frame($1).width * frame($1).height }).first else { throw Failure("No scroll area.") }; return area
    }
    static func wheel(_ direction: String, _ spot: CGPoint, _ a: NSRunningApplication, fraction: Double = 1, front: Bool = false) throws {
        guard env["RABIK_AX_ONLY"] != "1" else { throw Failure("Quartz mouse actions disabled for this fixture.") }
        let pid = a.processIdentifier, window = targetWindow(a)
        if front || window == 0 || MiniScreen.workInFront { return try frontWheel(direction, spot, a, fraction: fraction) }
        guard let source = CGEventSource(stateID: .hidSystemState) else { throw Failure("Could not create scroll event.") }
        let vertical = ["down","up"].contains(direction), amount = Int32(((["down","right"].contains(direction) ? -500.0 : 500.0) * fraction).rounded())
        guard let move = CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: spot, mouseButton: .left),
              let event = CGEvent(scrollWheelEvent2Source: source, units: .pixel, wheelCount: 2, wheel1: vertical ? amount : 0, wheel2: vertical ? 0 : amount, wheel3: 0) else { throw Failure("Could not create scroll event.") }
        deliver(move, at: spot, pid: pid, window: window); usleep(12_000)   // the wheel goes to whatever the window last saw under the pointer
        deliver(event, at: spot, pid: pid, window: window)
    }
    static func contentMoved(_ before: Map, _ after: Map) -> Bool {
        let changedText = Set(before.texts).subtracting(after.texts).count >= 3 && Set(after.texts).subtracting(before.texts).count >= 3
        return changedText || before.nodes.contains { n in
            let hits = after.nodes.filter { $0.role == n.role && $0.label == n.label }
            return hits.count == 1 && hypot(n.spot.x - hits[0].spot.x,n.spot.y - hits[0].spot.y) >= 6
        }
    }
    static func pageKeysAllowed(_ a: NSRunningApplication) -> Bool {
        guard let focused = element(AXUIElementCreateApplication(a.processIdentifier),kAXFocusedUIElementAttribute), let role = attribute(focused,kAXRoleAttribute) as? String else { return false }
        return ["AXWebArea","AXScrollArea","AXGroup","AXLayoutArea","AXWindow","AXTable","AXOutline","AXRow","AXCell","AXBrowser","AXStaticText","AXHeading","AXLink","AXButton","AXImage"].contains(role)
    }
    static func scroll(_ direction: String, pages: Double, all: Bool, a: NSRunningApplication, target: CGPoint? = nil) throws -> String {
        guard ["down","up","left","right"].contains(direction), pages.isFinite && pages >= 0.1 && pages <= 50 else { throw Failure("Use scroll down|up|left|right [pages|all] [target].") }
        let area = try (try? scrollArea(a, target: target)) ?? root(a).1, bar = element(area, ["down","up"].contains(direction) ? kAXVerticalScrollBarAttribute : kAXHorizontalScrollBarAttribute)
        let positive = ["down","right"].contains(direction), end = positive ? 1.0 : 0.0
        var moved = false, performed = 0, atEnd = false
        let fraction = min(1,pages)
        for _ in 0..<(all ? 50 : Int(ceil(pages))) {
            try checkStopped()
            let before = try capture(a), value = bar.flatMap { attribute($0, kAXValueAttribute) as? NSNumber }?.doubleValue
            let pixels = value == nil && env["RABIK_AX_ONLY"] != "1" ? fingerprint(before) : []
            if let value, abs(value - end) < 0.001 { atEnd = true; break }
            var methods: [() throws -> Void] = [
                { if fraction == 1 { _ = perform(area, ["AXScroll\(direction.capitalized)ByPage"]) } },
                { if let bar { _ = perform(bar, [positive ? "AXIncrement" : "AXDecrement"]) } },
                { if let bar, let value { _ = AXUIElementSetAttributeValue(bar, kAXValueAttribute as CFString, NSNumber(value: all ? end : max(0,min(1,value + (positive ? 0.15 : -0.15) * fraction)))) } },
                { if fraction == 1 && pageKeysAllowed(a) { try sendKeys(["down":"pagedown","up":"pageup","left":"left","right":"right"][direction]!, pid: a.processIdentifier) } },
                { if env["RABIK_AX_ONLY"] != "1" { try wheel(direction, target ?? CGPoint(x: frame(area).midX,y: frame(area).midY), a, fraction:fraction) } },
                { if env["RABIK_AX_ONLY"] != "1" { try wheel(direction, CGPoint(x: frame(area).midX,y: positive ? frame(area).maxY - 10 : frame(area).minY + 10), a, fraction:fraction) } },
                { if env["RABIK_AX_ONLY"] != "1" { try wheel(direction, target ?? CGPoint(x: frame(area).midX,y: frame(area).midY), a, fraction:fraction, front:true) } }
            ]
            // AX and PID-key paths first; the background wheel next; the foreground wheel only after nothing else moved.
            if all, let bar { var writable = DarwinBoolean(false); AXUIElementIsAttributeSettable(bar,kAXValueAttribute as CFString,&writable); if writable.boolValue { methods.insert({ _ = AXUIElementSetAttributeValue(bar,kAXValueAttribute as CFString,NSNumber(value:end)) },at:0) } }
            var changed = false
            for method in methods {
                try checkStopped(); try method()
                for poll in 0..<3 {
                    usleep(poll == 0 ? 25_000 : 75_000)
                    let after = try capture(a), newValue = bar.flatMap { attribute($0, kAXValueAttribute) as? NSNumber }?.doubleValue
                    if (value != nil && newValue != nil ? abs(newValue! - value!) >= 0.001 : contentMoved(before,after) || (!pixels.isEmpty && pixelsChanged(pixels, fingerprint(after)))) { changed = true; break }
                }
                if changed { break }
            }
            if !changed { break }; moved = true; performed += 1
            if all, let newValue = bar.flatMap({ attribute($0, kAXValueAttribute) as? NSNumber })?.doubleValue, abs(newValue - end) < 0.001 { break }
        }
        let percent = bar.flatMap { attribute($0,kAXValueAttribute) as? NSNumber }.map { " (now \(Int($0.doubleValue * 100))%)" } ?? ""
        return moved ? "Scrolled \(direction) " + (fraction < 1 ? "a bit" : "\(performed) page\(performed == 1 ? "" : "s")") + percent : atEnd ? "Already at the end" : "No scroll movement detected"
    }
    static func findText(_ text: String, _ a: NSRunningApplication) throws -> AXUIElement? {
        let (_, w) = try root(a), start = Date(); var queue = [w], i = 0, best: AXUIElement?, score = 0
        while i < queue.count && i < 6000 && Date().timeIntervalSince(start) < 1 {
            try checkStopped()
            let e = queue[i]; i += 1; let role = attribute(e,kAXRoleAttribute) as? String ?? ""
            if !["AXTextField","AXTextArea","AXSecureTextField"].contains(role) { let r = rank(name(e), text); if r > score { best = e; score = r }; if r == 4 { return e } }
            queue += children(e)
        }
        return best
    }
    static func scrollTo(_ text: String, _ a: NSRunningApplication) throws -> String {
        func visible() throws -> Bool {
            let m = try capture(a)
            return m.texts.contains(where: { rank($0,text) == 4 }) || m.nodes.contains(where: { rank($0.label,text) == 4 })
        }
        if try visible() { return "Found \(quote(mask(text)))" }
        let found = try findText(text,a)
        if let e = found, perform(e,["AXScrollToVisible"]) {
            for _ in 0..<4 { usleep(25_000); if try visible() { return "Revealed \(quote(mask(text)))" } }
        }
        var direction = "down", reversed = false, target: CGPoint?, limit = 15
        if var e = found {
            for _ in 0..<40 {
                if attribute(e,kAXRoleAttribute) as? String == "AXScrollArea" {
                    let bounds = frame(e); target = CGPoint(x:bounds.midX,y:bounds.midY)
                    if let found, frame(found).maxY < bounds.minY { direction = "up" }
                    if let found, bounds.height > 0 { limit = min(60, max(15, Int(abs(frame(found).midY - bounds.midY) / bounds.height) + 3)) }   // far text: enough pages to reach it
                    break
                }
                guard let parent = element(e,kAXParentAttribute) else { break }; e = parent
            }
        }
        for _ in 0..<limit {
            try checkStopped()
            let m = try capture(a)
            if m.texts.contains(where: { rank($0,text) == 4 }) || m.nodes.contains(where: { rank($0.label,text) == 4 }) { return "Found \(quote(mask(text)))" }
            let result = try scroll(direction,pages: 1,all: false,a: a,target:target)
            if result == "Already at the end" { if reversed { break }; direction = direction == "down" ? "up" : "down"; reversed = true }
            else if result == "No scroll movement detected" { break }
        }
        if try visible() { return "Found \(quote(mask(text)))" }
        throw Failure("Could not find \(quote(mask(text))) within \(limit) pages.")
    }
    static func stringValue(_ e: AXUIElement) -> String? {
        let raw = attribute(e,kAXValueAttribute)
        return raw as? String ?? (raw as? NSAttributedString)?.string
    }
    static func selectedRange(_ e: AXUIElement) -> CFRange? {
        guard let value = attribute(e,kAXSelectedTextRangeAttribute), CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
        var range = CFRange()
        return AXValueGetValue(value as! AXValue,.cfRange,&range) ? range : nil
    }
    static func insertionTarget(_ text: String, _ a: NSRunningApplication) throws -> Insertion {
        guard !text.isEmpty else { throw Failure("The anchor text is empty.") }
        let (_, w) = try root(a), start = Date(); var queue = [w], cursor = 0
        var fields: [(AXUIElement,String,CGRect)] = [], anchors: [AXUIElement] = []
        while cursor < queue.count && cursor < 6000 && Date().timeIntervalSince(start) < 1 {
            try checkStopped()
            let item = queue[cursor]; cursor += 1
            let role = attribute(item,kAXRoleAttribute) as? String ?? "", bounds = visibleFrame(item)
            if let value = stringValue(item), ["AXTextField","AXTextArea","AXComboBox","AXSearchField"].contains(role) {
                fields.append((item,value,bounds))
            }
            let value = stringValue(item) ?? ""
            if rank(name(item),text) == 4 || (!value.isEmpty && (value as NSString).range(of:text).location != NSNotFound) {
                if !anchors.contains(where:{ CFEqual($0,item) }) { anchors.append(item) }
            }
            queue += children(item)
        }
        let inside = fields.compactMap { field, old, _ -> Insertion? in
            let source = old as NSString, hit = source.range(of:text)
            guard hit.location != NSNotFound,
                  source.range(of:text,options:[],range:NSRange(location:hit.location + hit.length,length:source.length - hit.location - hit.length)).location == NSNotFound else { return nil }
            return Insertion(field:field,anchor:field,old:old,location:hit.location + hit.length,label:text)
        }
        if inside.count == 1 { return inside[0] }
        if inside.count > 1 { throw Failure("More than one editable passage contains \(quote(mask(text))). Use a longer exact anchor.") }
        let exact = anchors.filter { rank(name($0),text) == 4 }
        let matches = exact.isEmpty ? anchors : exact
        guard let anchor = matches.min(by: {
            let left = visibleFrame($0), right = visibleFrame($1)
            return left.width * left.height < right.width * right.height
        }) else { throw Failure("No readable text matches \(quote(mask(text))). Read the window again.") }
        let ar = visibleFrame(anchor)
        guard matches.allSatisfy({ visibleFrame($0).intersects(ar) }) else { throw Failure("More than one passage matches \(quote(mask(text))). Use a longer exact anchor.") }
        let empty = fields.filter { $0.1.isEmpty && !$0.2.isNull && $0.2.width >= 4 && $0.2.height >= 4 }.compactMap { item -> (Double,(AXUIElement,String,CGRect))? in
            let r = item.2, sameLine = abs(r.midY - ar.midY) <= max(r.height,ar.height)
            if sameLine && r.midX >= ar.midX { return (r.minX - ar.maxX,item) }
            if r.midY >= ar.midY { return (10_000 + (r.midY - ar.midY) * 10 + abs(r.minX - ar.minX),item) }
            return nil
        }.sorted { $0.0 < $1.0 }
        guard let field = empty.first?.1 else { throw Failure("No empty editable area follows \(quote(mask(text))).") }
        return Insertion(field:field.0,anchor:anchor,old:field.1,location:0,label:text)
    }
    static func insertAfter(_ text: String, _ draft: String, _ a: NSRunningApplication) throws -> String {
        let target = try insertionTarget(text,a), source = target.old as NSString
        let expected = source.replacingCharacters(in:NSRange(location:target.location,length:0),with:draft)
        guard AXUIElementSetAttributeValue(target.field,kAXFocusedAttribute as CFString,kCFBooleanTrue) == .success else { throw Failure("Could not focus the answer location.") }
        var range = CFRange(location:target.location,length:0)
        guard let value = AXValueCreate(.cfRange,&range),
              AXUIElementSetAttributeValue(target.field,kAXSelectedTextRangeAttribute as CFString,value) == .success,
              selectedRange(target.field).map({ $0.location == range.location && $0.length == 0 }) == true else { throw Failure("Could not verify the caret after \(quote(mask(text))).") }
        let write = AXUIElementSetAttributeValue(target.field,kAXSelectedTextAttribute as CFString,draft as CFString)
        if write == .success {
            guard stringValue(target.field) == expected else { throw Failure("Text changed outside the verified caret; undo before continuing.") }
        } else {
            let clipboard = try lease("clipboard.lock"); defer { unlock(clipboard) }   // one clipboard borrower at a time, across Rabik processes
            guard stringValue(target.field) == target.old, selectedRange(target.field).map({ $0.location == range.location && $0.length == 0 }) == true else { throw Failure("The document changed before typing.") }
            let pb = NSPasteboard.general, saved = pb.pasteboardItems?.map { i in i.types.compactMap { t in i.data(forType:t).map { (t,$0) } } } ?? []
            pb.clearContents(); guard pb.setString(draft,forType:.string) else { throw Failure("Could not prepare paste.") }; let changed = pb.changeCount
            defer { if pb.changeCount == changed { pb.clearContents(); pb.writeObjects(saved.map { pairs in let i=NSPasteboardItem(); pairs.forEach { i.setData($1,forType:$0) }; return i }) } }
            try sendKeys("cmd+v",pid:a.processIdentifier); usleep(150_000)
            guard stringValue(target.field) == expected else { throw Failure("Could not verify that the original text was preserved.") }
        }
        guard stringValue(target.anchor).map({ ($0 as NSString).range(of:text).location != NSNotFound }) ?? (rank(name(target.anchor),text) == 4) else { throw Failure("The anchor text changed; undo before continuing.") }
        return "Typed after \(quote(mask(text)))"
    }
    static func typeText(_ text: String, _ n: Node, _ e: AXUIElement, _ a: NSRunningApplication, append: Bool) throws {
        guard ["AXTextField","AXTextArea","AXComboBox","AXSearchField","AXSecureTextField"].contains(n.role) else { throw Failure("Target is not a text field.") }
        guard AXUIElementSetAttributeValue(e,kAXFocusedAttribute as CFString,kCFBooleanTrue) == .success else { throw Failure("Could not focus that field.") }
        let old = attribute(e,kAXValueAttribute) as? String ?? "", draft = append ? old + text : text
        if AXUIElementSetAttributeValue(e,kAXValueAttribute as CFString,draft as CFString) == .success {
            guard attribute(e,kAXValueAttribute) as? String == draft else { throw Failure("Text did not land in the field.") }; return
        }
        let clipboard = try lease("clipboard.lock"); defer { unlock(clipboard) }   // one clipboard borrower at a time, across Rabik processes
        guard attribute(e,kAXValueAttribute) as? String ?? "" == old else { throw Failure("The field changed before typing. Run see again.") }
        // Cmd-Right only reaches the end of the caret's line, so place and verify the caret at the value's end.
        var end = CFRange(location:(old as NSString).length,length:0)
        if append { guard let value = AXValueCreate(.cfRange,&end), AXUIElementSetAttributeValue(e,kAXSelectedTextRangeAttribute as CFString,value) == .success,
                          selectedRange(e).map({ $0.location == end.location && $0.length == 0 }) == true else { throw Failure("Could not verify the caret at the end of that field.") } }
        // PID-directed paste keeps focus in the user’s app; verify the same field before reporting success.
        let pb = NSPasteboard.general, saved = pb.pasteboardItems?.map { i in i.types.compactMap { t in i.data(forType:t).map { (t,$0) } } } ?? []
        pb.clearContents(); guard pb.setString(text,forType:.string) else { throw Failure("Could not prepare paste.") }; let changed = pb.changeCount
        defer { if pb.changeCount == changed { pb.clearContents(); pb.writeObjects(saved.map { pairs in let i = NSPasteboardItem(); pairs.forEach { i.setData($1,forType:$0) }; return i }) } }
        if !append { try sendKeys("cmd+a",pid:a.processIdentifier) }
        try sendKeys("cmd+v",pid:a.processIdentifier); usleep(150_000)
        if !n.secret, attribute(e,kAXValueAttribute) as? String != draft { throw Failure("Could not verify the pasted text.") }
    }
    static func settle(_ a: NSRunningApplication, seconds: Double) throws -> Bool {
        let start = Date(), initial = try capture(a); var last = initial.settled, since = Date()
        let usePixels = !initial.rich && env["RABIK_AX_ONLY"] != "1"
        var pixels = usePixels ? fingerprint(initial) : []
        while Date().timeIntervalSince(start) < seconds {
            try checkStopped()
            usleep(50_000); let map = try capture(a), current = map.settled
            let freshPixels = usePixels ? fingerprint(map) : []
            if current != last || pixelsChanged(pixels,freshPixels,threshold:1.5) { since = Date(); last = current }
            pixels = freshPixels
            if Date().timeIntervalSince(since) >= 0.3 { return true }
        }
        return false
    }
    // A receipt tied to this submission: the field let go of its draft (not just a new line in it), the page or window moved on,
    // or the sent words appeared as new text. Another control updating elsewhere in the window is not a receipt.
    static func submitReceipt(_ typed: String?, _ value: String?, _ sent: String, _ before: Map, _ after: Map) -> Bool {
        let consumed = typed.map { typed in value.map { $0 != typed && !$0.hasPrefix(typed) } ?? true } ?? false
        let posted = !sent.isEmpty && after.texts.contains { $0.contains(sent) } && !before.texts.contains { $0.contains(sent) }
        return consumed || posted || after.page != before.page || after.windowID != before.windowID
    }
    static func validate(_ args: [String]) throws {
        guard let verb = args.first else { throw Failure("Use see|click|scroll|scroll-to|press|drag|type|wait.") }
        let rest = Array(args.dropFirst())
        guard !rest.contains(where: { $0.hasPrefix("--") }) else { throw Failure("Hands accepts no flags.") }
        switch verb {
        case "menu": guard rest.count == 2, !rest[0].isEmpty, rest[1].components(separatedBy:">").count > 1, rest[1].components(separatedBy:">").allSatisfy({ !$0.trimmingCharacters(in:.whitespaces).isEmpty }) else { throw Failure("Use menu app path.") }
        case "see": guard rest.count <= 1 else { throw Failure("Use see [app].") }
        case "click": guard !rest.isEmpty, rest.count <= 6 else { throw Failure("Use click target [near label] [double] [right] [front].") }; _ = try clickOptions(rest)
        case "scroll": guard (1...3).contains(rest.count), ["down","up","left","right"].contains(rest[0]), rest.count < 3 || rest[1] == "all" || Double(rest[1]).map({ $0.isFinite && $0 >= 0.1 && $0 <= 50 }) == true else { throw Failure("Use scroll direction [pages|all] [target].") }; if rest.count == 2, let n = Double(rest[1]), !n.isFinite || n < 0.1 || n > 50 { throw Failure("Invalid page count.") }
        case "scroll-to": guard rest.count == 1 else { throw Failure("Use scroll-to text.") }
        case "press": guard (1...2).contains(rest.count) else { throw Failure("Use press keys [times].") }; _ = try keys(rest[0]); if rest.count == 2 { guard let n = Int(rest[1]), (1...50).contains(n) else { throw Failure("Invalid repeat count.") } }
        case "drag": guard rest.count == 2 else { throw Failure("Use drag from to.") }
        case "type": guard (2...4).contains(rest.count), rest.dropFirst(2).allSatisfy({ ["submit","append"].contains($0) }) else { throw Failure("Use type target text [submit] [append].") }
        case "type-after": guard rest.count == 2, !rest[0].isEmpty else { throw Failure("Use type-after anchor text.") }
        case "wait": guard rest.count <= 1, rest.isEmpty || Double(rest[0]).map({ $0.isFinite && $0 > 0 && $0 <= 30 }) == true else { throw Failure("Use wait [seconds, max 30].") }
        default: throw Failure("Unknown hands verb: \(verb)")
        }
    }
    static func clickOptions(_ args: [String]) throws -> (String,Bool,Bool,Bool) {
        var near = "", double = false, right = false, front = false, i = 1
        while i < args.count {
            switch args[i] {
            case "near": guard i + 1 < args.count, near.isEmpty else { throw Failure("Use near label.") }; near = args[i+1]; i += 1
            case "double": guard !double else { throw Failure("Duplicate double.") }; double = true
            case "right": guard !right else { throw Failure("Duplicate right.") }; right = true
            case "front": guard !front else { throw Failure("Duplicate front.") }; front = true
            default: throw Failure("Unknown click option: \(args[i])")
            }; i += 1
        }
        return (near,double,right,front)
    }
    static func targets(_ args: [String]) -> [String] {
        switch args[0] {
        case "click", "type", "type-after": return [args[1]]
        case "drag": return [args[1],args[2]]
        case "scroll": return args.count == 4 ? [args[3]] : args.count == 3 && args[2] != "all" && Double(args[2]) == nil ? [args[2]] : []
        default: return []
        }
    }
    static func freshIDs(_ args: [String], _ old: Map, _ fresh: Map) throws {
        if targets(args).contains(where: { Int($0) != nil }), old.signature != fresh.signature { throw Failure("The screen changed. Run see again.") }
    }
    static func targetsCurrent(_ args: [String], _ map: Map, _ a: NSRunningApplication) -> Bool {
        do {
            let (_, window) = try root(a)
            guard array(frame(window)) == map.windowFrame, mask(name(window)) == mask(map.window) else { return false }
            if let id = axWindowNumber(window)?.stringValue, !map.windowID.isEmpty, id != map.windowID { return false }
            if args[0] == "click", args[1].contains(">") {
                return try menu(args[1],a,act:false) == (try checked(args,map,a)["labels"] as? [String])?.last
            }
            if ["click","drag","type"].contains(args[0]) {
                let near = args[0] == "click" ? try clickOptions(Array(args.dropFirst())).0 : ""
                for target in (args[0] == "drag" ? [args[1],args[2]] : [args[1]]) {
                    let (node, element) = try resolve(target,map:map,a:a,near:near)
                    guard let element else { return false }
                    let role = attribute(element,kAXRoleAttribute) as? String ?? "", rawLabel = name(element)
                    let label = mask(rawLabel.isEmpty ? role : rawLabel)
                    guard role == node.role, label == node.label, array(visibleFrame(element)) == node.frame else { return false }
                    if args[0] == "type", !node.secret {
                        let raw = attribute(element,kAXValueAttribute)
                        let value = String(mask(raw as? String ?? (raw as? NSNumber)?.stringValue ?? "").prefix(400))
                        guard value == node.value else { return false }
                    }
                }
            } else if args[0] == "press" {
                guard let focused = element(AXUIElementCreateApplication(a.processIdentifier),kAXFocusedUIElementAttribute) else { return map.focused.isEmpty }
                let role = attribute(focused,kAXRoleAttribute) as? String ?? "", label = mask(name(focused))
                guard label == map.focused, map.focusIdentity.hasPrefix(role + ":"), map.focusIdentity.hasSuffix(":" + String(describing:array(frame(focused)))) else { return false }
            }
            return true
        } catch { return false }
    }
    static func checked(_ args: [String], _ map: Map, _ a: NSRunningApplication) throws -> [String: Any] {
        var labels: [String] = [], secure = false, at: [String] = []
        let verb = args[0]
        if verb == "click", args[1].contains(">") {
            let (near,double,right,front) = try clickOptions(Array(args.dropFirst()))
            guard near.isEmpty && !double && !right && !front else { throw Failure("Menu paths accept no click options.") }
            labels = args[1].components(separatedBy:">").dropLast().map { mask($0.trimmingCharacters(in:.whitespaces)) } + [try menu(args[1],a,act:false)]
        }
        else if ["click","drag","type"].contains(verb) {
            let near = verb == "click" ? try clickOptions(Array(args.dropFirst())).0 : ""
            for target in (verb == "drag" ? [args[1],args[2]] : [args[1]]) { let (n, _) = try resolve(target,map:map,a:a,near:near); labels.append(n.label); at.append("\(n.frame)"); secure = secure || n.secret }
        } else if verb == "type-after" {
            let target = try insertionTarget(args[1],a); labels = [target.label]; secure = secret(name(target.field))
        } else if verb == "press" {
            labels = [map.focused,args[1]] + (menuShortcut(args[1],a).map { [$0.1] } ?? []); at = [map.focusIdentity]
            let (code, _) = try keys(args[1])
            if [CGKeyCode(51),CGKeyCode(117)].contains(code),
               let focused = element(AXUIElementCreateApplication(a.processIdentifier),kAXFocusedUIElementAttribute),
               selectedRange(focused) != nil { throw Failure("Backspace cannot prove the text belongs to Rabik. Undo Rabik's last edit with cmd+z instead.") }
        }
        let keyRisk = verb == "press" ? try riskyKey(args[1]) : false
        let risk = labels.contains { $0.hasPrefix("Unidentified screen point ") || riskyLabel($0,map) || (verb == "drag" && matches($0,#"(?i)\b(bin|recycle)\b"#)) } || keyRisk || (verb == "type" && args.dropFirst(3).contains("submit"))
        // The approval covers the target and its window, not the whole tree: a clock, or a neighbour an app builds lazily after first contact, must not void it.
        return ["labels":labels,"secure":secure,"risky":risk,"at":at,"pid":map.pid,"args":args,"windowID":map.windowID,"windowFrame":map.windowFrame,"window":mask(map.window),"app":map.app]
    }
    static func cli(_ input: [String]) -> Int32 {
        defer { restoreAccessibility() }
        let started = DispatchTime.now().uptimeNanoseconds
        defer {
            if env["RABIK_HANDS_TIMING"] == "1" {
                let ms = Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000
                FileHandle.standardError.write(Data("HANDS NET \(String(format:"%.2f",ms)) ms\n".utf8))
            }
        }
        stopped = 0
        signal(SIGTERM) { _ in Hands.stopped = 1 }; signal(SIGINT) { _ in Hands.stopped = 1 }
        do {
            if input.first == "label" { let args = Array(input.dropFirst()); try validate(args); try trusted(); let old = try load(), a = try aimed(args, old), m = try capture(a); try freshIDs(args,old,m); let checked = try checked(args, m, a); print(String(data:try JSONSerialization.data(withJSONObject:checked),encoding:.utf8)!); return 0 }
            if input.first == "identify" {
                guard input.count <= 2 else { throw Failure("Use identify [app].") }
                try trusted()
                print(String(data: try JSONSerialization.data(withJSONObject: identify(try app(input.count > 1 ? input[1] : nil))), encoding: .utf8)!); return 0
            }
            if input.first == "read" {
                guard input.count <= 3 && (input.count < 3 || input[2] == "more") else { throw Failure("Use read [app] [more].") }
                try trusted()
                let text = try read(try app(input.count > 1 ? input[1] : nil), more: input.count == 3, head: env["RABIK_HANDS_HEAD"] == "1")
                print(String(data: try JSONSerialization.data(withJSONObject: text), encoding: .utf8)!); return 0
            }
            try validate(input); try trusted()
            if input[0] == "see" { let m = try capture(try app(input.count > 1 ? input[1] : nil)); try save(m); print(m.description); return 0 }
            if input[0] == "menu" {
                let a = try app(input[1]), label = try menu(input[2],a,act:false)
                guard !Prefs.bool("safe") || !(riskyLabel(input[2]) || riskyLabel(label)) else { throw Failure("This menu action needs the user's Allow card. Use the normal hands click path.") }
                claims = true; if userWindowsFile != nil { _ = try? root(a) }   // a menu command acts in the app's focused window: it claims that one
                let target = MiniScreen.windowTarget(a,windows:CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? [])   // optional AX metadata must not turn a successful press into a timeout and duplicate action
                print("Clicked \(quote(try menu(input[2],a,act:true)))")
                if let target,
                   let data = try? JSONSerialization.data(withJSONObject:target.merging(["action":"click"]) { $1 }), let text = String(data:data,encoding:.utf8) { print("▣ " + text) }
                return 0
            }
            claims = ["click","drag","type","type-after","press"].contains(input[0])
            let old = try load(), a = try aimed(input, old); var before = try capture(a)
            let check = try checked(input, before, a)
            try freshIDs(input,old,before)
            if env["RABIK_HANDS_SESSION"] == "1" {
                print(String(data:try JSONSerialization.data(withJSONObject:check),encoding:.utf8)!); fflush(stdout)
                let answer = String(data:FileHandle.standardInput.readDataToEndOfFile(),encoding:.utf8)?.trimmingCharacters(in:.whitespacesAndNewlines)
                guard answer == "y" else { throw Failure("Action cancelled.") }
                if !targetsCurrent(input,before,a) {
                    let fresh = try capture(a), refreshed = try checked(input,fresh,a)
                    guard NSDictionary(dictionary:refreshed).isEqual(to:check) else {
                        try save(fresh); throw Failure("The screen changed while checking permission. Run see again.")
                    }
                    before = fresh
                }
            } else {
                let data = env["RABIK_HANDS_RECEIPT"] == "1" ? FileHandle.standardInput.readDataToEndOfFile() : Data()
                let receipt = (try? JSONSerialization.jsonObject(with:data)) as? [String:Any]
                if let receipt {
                    guard NSDictionary(dictionary:receipt).isEqual(to:check) else { throw Failure("The screen changed while checking permission. Run see again.") }
                } else if (check["risky"] as? Bool == true && Prefs.bool("safe")) || (input[0] == "type" && check["secure"] as? Bool == true) { throw Failure("Use rabik.py --hands so the user can allow this action.") }
            }
            // One app's input stays whole: another task's action in the same app finishes first, then this target is checked again.
            let inputLock = input[0] == "wait" ? nil : try lease("hands-\(a.bundleIdentifier ?? String(a.processIdentifier)).lock"); defer { if let inputLock { unlock(inputLock) } }
            if inputLock != nil && leaseWaited && !targetsCurrent(input,before,a) { throw Failure("Another task changed this window while this one waited. Nothing was done; run see again.") }
            // Background first; the real pointer for work the user asked to see or a window without a known id. An app can take a
            // background gesture without any visible change, so one is never repeated in front by itself: the reply says how to redo it.
            var background = false
            func gesture(_ asked: Bool = false, _ act: (Bool) throws -> Void) throws {
                let front = asked || MiniScreen.workInFront || targetWindow(a) == 0
                try act(front); background = !front
            }
            var result = "", spot: CGPoint?, spotPixels: [UInt8] = []
            let exact = input[0] == "click" ? try point(input[1]) : nil
            switch input[0] {
            case "click":
                if input[1].contains(">") { let label = try menu(input[1],a,act:true); result = "Clicked \(quote(label))" }
                else {
                    let (near,double,right,front) = try clickOptions(Array(input.dropFirst())), (n,e) = try resolve(input[1],map:before,a:a,near:near), at = exact ?? n.spot; spot = at
                    // Pressing the element around an unmapped point clicks its center, not the point.
                    if let e, exact == nil || n.id != 0, !double && !right && !front, perform(e,["AXPress","AXPick","AXConfirm","AXOpen"]) { }
                    else {
                        // A mouse click can change only pixels (a canvas, a map, a video); they show whether it took.
                        if env["RABIK_AX_ONLY"] != "1" { spotPixels = fingerprint(before, around: at) }
                        try gesture(front) { try mouse(at,a,double:double,right:right,front:$0) }
                    }
                    result = "Clicked \(quote(n.label))"
                }
            case "scroll":
                let amount = input.count > 2 ? input[2] : "1", pages = Double(amount) ?? 1
                let target = input.count > 3 ? input[3] : (input.count > 2 && amount != "all" && Double(amount) == nil ? amount : "")
                let p = target.isEmpty ? nil : try resolve(target,map:before,a:a).0.spot
                spot = p ?? CGPoint(x:before.windowFrame[0] + before.windowFrame[2] / 2,y:before.windowFrame[1] + before.windowFrame[3] / 2)
                result = try scroll(input[1],pages:pages,all:amount == "all",a:a,target:p)
            case "scroll-to": result = try scrollTo(input[1],a)
            case "press":
                let times = input.count > 2 ? Int(input[2])! : 1
                if let (item, label) = menuShortcut(input[1],a) {
                    try keysReachTask(a.processIdentifier)   // the menu command acts on the app's focused window, so it must be this task's
                    let lease = try screenLease(); defer { unlock(lease) }   // as menu(): a press can bring the app forward, so put the user's app back
                    DistributedNotificationCenter.default().postNotificationName(.init("rabik.raise"), object: nil, deliverImmediately: true)
                    usleep(50_000); let restore = restoreFocus(a); defer { usleep(30_000); restore() }
                    for _ in 0..<times { try checkStopped(); guard perform(item,["AXPress"]) else { throw Failure("Could not run \(quote(label)).") }; usleep(15_000) }
                    result = "Ran \(quote(label)) for \(quote(input[1])) in \(a.localizedName ?? "app")"
                } else { try sendKeys(input[1],pid:a.processIdentifier,times:times); result = "Pressed \(quote(input[1])) in \(a.localizedName ?? "app")" }
            case "drag": let from = try resolve(input[1],map:before,a:a).0, to = try resolve(input[2],map:before,a:a).0; try gesture { try mouse(from.spot,a,to:to.spot,front:$0) }; spot = to.spot; result = "Dragged \(quote(from.label)) to \(quote(to.label))"
            case "type":
                let (n,e) = try resolve(input[1],map:before,a:a); guard let e else { throw Failure("No editable field.") }
                spot = n.spot; try typeText(input[2],n,e,a,append:input.dropFirst(3).contains("append"))
                if input.dropFirst(3).contains("submit") {
                    let typed = stringValue(e), submitted = try capture(a), deadline = Date().addingTimeInterval(0.5), sent = mask(String(input[2].prefix(60)))
                    try sendKeys("return",pid:a.processIdentifier)
                    var accepted = false
                    repeat {
                        usleep(50_000)
                        accepted = submitReceipt(typed, stringValue(e), sent, submitted, try capture(a))
                    } while !accepted && Date() < deadline
                    if !accepted { throw Failure("Could not verify Return was accepted in the background. Read the window; if it was not sent, click its send button.") }
                }
                result = "Typed into \(quote(n.label))"
            case "type-after": result = try insertAfter(input[1],input[2],a)
            case "wait": result = try settle(a,seconds:input.count > 1 ? Double(input[1])! : 5) ? "Window settled" : "Window did not settle before the timeout"
            default: throw Failure("Unknown hands verb.")
            }
            if input[0] != "wait" { usleep(25_000) }
            let after = try capture(a)
            if input[0] == "click" {
                let (_, w) = try root(a)
                var known = before; if known.page.isEmpty { known.page = after.page }   // a page the reader had not reached yet (a browser builds it lazily) is not a change
                let same = after.signature == known.signature
                if let sheet = (attribute(w,"AXSheets") as? [AXUIElement])?.first ?? (attribute(w,kAXRoleAttribute) as? String == "AXSheet" ? w : nil) { result += " — a sheet opened: \(quote(mask(name(sheet))))" }
                else if same, let spot, !spotPixels.isEmpty, pixelsChanged(spotPixels, fingerprint(after, around: spot), threshold: 1.5) { result += " — the screen changed at that spot" }
                // A background click the screen could not be read for (its window covered, or on another Space): say what happened, not "nothing changed".
                else if same, background, spotPixels.isEmpty { result += " in the background. Its spot could not be read to confirm a change (the window may be covered or on another Space); read the window, or add front to the same click to bring it forward for that click only" }
                // front only on evidence: neither the accessibility tree nor the pixels at the spot changed after a background click
                else if same { result = "Nothing changed after clicking \(quote((check["labels"] as? [String])?.first ?? input[1]))" + (background && !spotPixels.isEmpty ? ". It went in the background; if this app ignores background clicks, add front to the same click: the app comes forward for that click only, then the user's app returns" : "") }
            }
            print(result)
            if let spot { print("@ \(Int(spot.x)) \(Int(spot.y))") }
            let changed = after.nodes.filter { n in !before.nodes.contains { $0.id == n.id && $0.path == n.path && $0.role == n.role && $0.label == n.label && $0.value == n.value && $0.frame == n.frame } }
            let removed = before.nodes.filter { n in !after.nodes.contains { $0.id == n.id && $0.path == n.path && $0.role == n.role && $0.label == n.label } }.map { "Removed: [\($0.id)] \(quote($0.label))" }
            if after.windowID != before.windowID || after.window != before.window || after.windowFrame != before.windowFrame { print(after.description) }
            else { print((["Now: \(mask(after.window))"] + removed + changed.map(\.line) + ["Focused: \(after.focused)"] + (after.scroll.isEmpty ? [] : ["Scroll: \(Int(after.scroll[0] * 100))% down"]) + (after.page == before.page ? [] : ["Page: \(mask(after.page))"]) + [String(after.texts.filter { !before.texts.contains($0) }.joined(separator:" | ").prefix(1400))]).joined(separator:"\n")) }
            try save(after); return 0
        } catch let failure as Failure { print(failure.message); return 1 }
        catch { print("Hands could not finish: \(error.localizedDescription)"); return 1 }
    }
    static func selftest() {
        precondition(rank("Export", "") == 0)
        precondition(rank("Export","export") == 4 && rank("Export PDF","export") == 3 && rank("Start Export Now","export") == 2 && rank("Reexport","export") == 1)
        precondition(try! point("first, second") == nil)
        precondition(mask("4111 1111 1111 1111 / 123-45-6789 / Code 123456") == "[SECRET] / [SECRET] / Code [SECRET]")
        precondition(secret("Password") && secret("one time code") && !secret("Name"))
        let date = "Oct 11, 2026 6:39 PM"
        precondition(!secret(date) && mask(date) == date && !secret("Version 12.34.5678"))
        precondition(mask("4111111111111111") == "[SECRET]")
        let safeMap = Map(pid:123,app:"Fixture",window:"Export options",windowFrame:[0,0,400,400],nodes:[],texts:["Choose a destination"],page:"",focused:"",scroll:[])
        var dangerousMap = safeMap; dangerousMap.texts = ["Delete 3 items?"]
        for label in ["OK","Yes","Continue","Allow","Accept","Agree","Complete","Finish","Grant"] { precondition(!riskyLabel(label,safeMap) && riskyLabel(label,dangerousMap)) }
        precondition(!riskyLabel("Cancel",dangerousMap) && riskyLabel("Confirm",safeMap) && riskyLabel("Allow access",safeMap))
        precondition(matches("Delete draft",riskyPattern) && matches("Send",riskyPattern) && !matches("Export",riskyPattern))
        precondition((try! keys("⌘+⇧+4")).0 == 21 && (try! keys("cmd++")).0 == 24)
        precondition(!(try! riskyKey("return")))
        precondition(try! riskyKey("cmd+q")); precondition(!(try! riskyKey("cmd+t")))
        let (code,flags) = try! keys("cmd+shift+4"); precondition(code == 21 && flags == [.maskCommand,.maskShift])
        precondition(digest(["count 1"],maskDigits:true) == digest(["count 2"],maskDigits:true))
        let node = Node(id:1,role:"AXTextField",label:"Password",value:"private",frame:[0,0,10,10],path:[],secret:true)
        precondition(!node.line.contains("private") && node.line.contains("[1]"))
        precondition(!pixelsChanged([],[]) && pixelsChanged([0,0],[5,5]))
        // A 2:x,y spot on a 1920-wide display at x=1470 is the external monitor in Saarth's Oct 21 case: 602,397 -> global 2373,595.
        precondition(picturePoint(602, 397, in: CGRect(x: 1470, y: 0, width: 1920, height: 1080)) == CGPoint(x: 2373, y: 595.5))
        precondition(picturePoint(0, 0, in: CGRect(x: 0, y: 0, width: 1280, height: 800)) == .zero && picturePoint(640, 400, in: CGRect(x: 0, y: 0, width: 1280, height: 800)) == CGPoint(x: 640, y: 400))
        for args in [["click","Export","--yes"],["press","cmd+q","0"],["type","Name","text","force"],["wait","nan"]] { do { try validate(args); preconditionFailure("Accepted invalid hands args") } catch {} }
    }
}
