// Activity history. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa

// Settings → Memory → Activity history (off until turned on): the window in front, read with Accessibility (its app, title, the
// document's file, a browser's page address), so "open the Figma file I had yesterday" works. No screenshots. A window looked at
// under 10 s, private and incognito windows, Tor, password managers, Rabik and the user's own Don't record list are never written,
// nor is time while the Mac is locked or idle. One file a day under ~/.config/rabik/activity/ (0600), kept 30 days.
final class Activity {
    static let never: Set<String> = ["org.torproject.torbrowser", "com.1password.1password", "com.agilebits.onepassword7", "com.bitwarden.desktop",
                                     "com.apple.keychainaccess", "com.apple.Passwords", "com.lastpass.LastPass", "com.dashlane.dashlanephonefinal"]
    static let browsers: Set<String> = ["com.apple.Safari", "com.google.Chrome", "com.brave.Browser", "com.microsoft.edgemac", "company.thebrowser.Browser",
                                        "company.thebrowser.dia", "com.vivaldi.Vivaldi", "com.operasoftware.Opera", "org.mozilla.firefox", "app.zen-browser.zen"]
    var folder: String { (Prefs.path as NSString).deletingLastPathComponent + "/activity" }
    private var current: [String: Any]?, timer: Timer?, locked = false, observers: [NSObjectProtocol] = []
    private let q = DispatchQueue(label: "rabik.activity")

    func sync() {   // follows the setting: Rabik's launch, and every change in Settings
        Prefs.bool("activity") ? start() : stop()
    }

    private func start() {
        guard timer == nil else { return }
        prune()
        let ws = NSWorkspace.shared.notificationCenter, dc = DistributedNotificationCenter.default()
        observers = [
            ws.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] _ in self?.sample() },
            ws.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { [weak self] _ in self?.close() },
            dc.addObserver(forName: .init("com.apple.screenIsLocked"), object: nil, queue: .main) { [weak self] _ in self?.locked = true; self?.close() },
            dc.addObserver(forName: .init("com.apple.screenIsUnlocked"), object: nil, queue: .main) { [weak self] _ in self?.locked = false; self?.sample() },
        ]
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in self?.sample() }
        sample()
    }

    private func stop() {
        guard timer != nil else { return }
        timer?.invalidate(); timer = nil; close()
        observers.forEach { NSWorkspace.shared.notificationCenter.removeObserver($0); DistributedNotificationCenter.default().removeObserver($0) }; observers = []
    }

    func clear() {   // Settings → Clear history
        q.async { [self] in current = nil; try? FileManager.default.removeItem(atPath: folder) }
    }

    private func sample() {
        guard timer != nil, AXIsProcessTrusted(), let front = NSWorkspace.shared.frontmostApplication else { return }
        let idle = [CGEventType.keyDown, .mouseMoved, .leftMouseDown, .scrollWheel].map { CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: $0) }.min() ?? 0
        let bundle = front.bundleIdentifier ?? "", pid = front.processIdentifier, name = front.localizedName ?? bundle
        let skipped = Set((Prefs.d["activityExclude"] as? [[String: String]] ?? []).compactMap { $0["id"] }).union(Activity.never).union([Bundle.main.bundleIdentifier ?? "com.rabik.app"])
        q.async { [self] in
            guard !locked, idle < 300, !skipped.contains(bundle), let row = Activity.window(pid, bundle: bundle, app: name) else { return flush(Date()) }
            let now = Date().timeIntervalSince1970
            if let c = current, Activity.same(c, row) { current?["end"] = now; return }
            flush(Date()); current = row.merging(["start": now, "end": now]) { $1 }
        }
    }

    private func close() { q.async { [self] in flush(Date()) } }

    // The entry so far ends now; written when it lasted 10 s or more.
    private func flush(_ now: Date) {
        guard var row = current else { return }
        current = nil
        row["end"] = max(row["end"] as? Double ?? 0, min(now.timeIntervalSince1970, (row["end"] as? Double ?? 0) + 10))   // up to the next sample
        guard (row["end"] as? Double ?? 0) - (row["start"] as? Double ?? 0) >= 10 else { return }
        let day = DateFormatter(); day.dateFormat = "yyyy-MM-dd"; day.locale = Locale(identifier: "en_US_POSIX")
        let path = folder + "/" + day.string(from: Date(timeIntervalSince1970: row["start"] as? Double ?? 0)) + ".jsonl"
        guard let data = try? JSONSerialization.data(withJSONObject: row), FileManager.default.fileExists(atPath: folder) || (try? FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])) != nil else { return }
        if !FileManager.default.fileExists(atPath: path) { FileManager.default.createFile(atPath: path, contents: nil, attributes: [.posixPermissions: 0o600]) }
        guard let h = FileHandle(forWritingAtPath: path) else { return }
        h.seekToEndOfFile(); h.write(data + Data("\n".utf8)); try? h.close()
    }

    private func prune() {
        q.async { [self] in
            let cutoff = DateFormatter(); cutoff.dateFormat = "yyyy-MM-dd"; cutoff.locale = Locale(identifier: "en_US_POSIX")
            let oldest = cutoff.string(from: Date().addingTimeInterval(-30 * 86400))
            for name in (try? FileManager.default.contentsOfDirectory(atPath: folder)) ?? [] where name.hasSuffix(".jsonl") && name < oldest + ".jsonl" {
                try? FileManager.default.removeItem(atPath: folder + "/" + name)
            }
        }
    }

    static func same(_ a: [String: Any], _ b: [String: Any]) -> Bool {
        ["bundle", "title", "url", "path"].allSatisfy { a[$0] as? String == b[$0] as? String }
    }

    // The focused window: title, its document's file, or a browser's page. nil for a private window or one without a title.
    static func window(_ pid: pid_t, bundle: String, app: String) -> [String: Any]? {
        let ax = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(ax, 0.3)
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(ax, kAXFocusedWindowAttribute as CFString, &value) == .success, let win = value else { return nil }
        let window = win as! AXUIElement
        let title = (attribute(window, kAXTitleAttribute) as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty, !isPrivate(title) else { return nil }
        var row: [String: Any] = ["app": app, "bundle": bundle, "title": String(title.prefix(300))]
        if let doc = attribute(window, kAXDocumentAttribute) as? String, let url = URL(string: doc), url.isFileURL { row["path"] = url.path }
        if browsers.contains(bundle), let page = webAddress(window) {
            guard let scheme = page.scheme?.lowercased(), ["http", "https"].contains(scheme) else { return row }
            row["url"] = String(page.absoluteString.prefix(2000))
        }
        return row
    }

    static func isPrivate(_ title: String) -> Bool {
        title.range(of: #"\b(Private Browsing|Private Window|Incognito|InPrivate)\b"#, options: [.regularExpression, .caseInsensitive]) != nil
    }

    static func attribute(_ e: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        return AXUIElementCopyAttributeValue(e, name as CFString, &value) == .success ? value : nil
    }

    // A browser window's page: the address of its web area, a few levels down (a bounded walk, never the whole tree).
    static func webAddress(_ window: AXUIElement) -> URL? {
        var queue: [(AXUIElement, Int)] = [(window, 0)], seen = 0
        while !queue.isEmpty, seen < 400 {
            let (e, depth) = queue.removeFirst(); seen += 1
            if attribute(e, kAXRoleAttribute) as? String == "AXWebArea" {
                if let url = attribute(e, kAXURLAttribute) as? URL { return url }
                if let text = attribute(e, kAXURLAttribute) as? String, let url = URL(string: text) { return url }
            }
            guard depth < 12, let children = attribute(e, kAXChildrenAttribute) as? [AXUIElement] else { continue }
            queue += children.map { ($0, depth + 1) }
        }
        return nil
    }
}
