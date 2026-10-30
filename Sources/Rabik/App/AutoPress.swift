// Watches that press a button. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa

// "If ChatGPT asks for permission, allow it" (brain/watcher.py --watch press, confirmed once on a card): every 2 s, in that app's
// windows and their dialogs, a button whose title is one the user named gets AXPress, until they stop it. No AI, no focus change, no
// pointer move, and never in Rabik's own windows. Each press is logged (watches-log.jsonl, Settings counts it) and, at most once a
// minute per watch, notified with how many.
final class AutoPress {
    var folder: String { (Prefs.path as NSString).deletingLastPathComponent }
    private var rows: [[String: Any]] = [], stamp: Date?, timer: Timer?, busy = false
    private var noticed: [String: Date] = [:], unsaid: [String: Int] = [:]
    private let q = DispatchQueue(label: "rabik.autopress")

    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.tick() }
    }

    // watches.json changes from the brain (a new watch, "stop watching"): read again only when it changed
    private func reload() {
        let path = folder + "/watches.json"
        let changed = (try? FileManager.default.attributesOfItem(atPath: path)[.modificationDate]) as? Date
        guard changed != stamp else { return }
        stamp = changed
        rows = ((try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: path)))) as? [[String: Any]] ?? [])
            .filter { $0["kind"] as? String == "press" && ($0["app"] as? String)?.isEmpty == false && ($0["labels"] as? [String])?.isEmpty == false }
    }

    private func tick() {
        reload()
        guard !rows.isEmpty, !busy, !Prefs.bool("paused"), AXIsProcessTrusted() else { return }
        let me = Bundle.main.bundleIdentifier ?? "com.rabik.app"
        let jobs: [(String, String, pid_t, [String])] = rows.flatMap { row -> [(String, String, pid_t, [String])] in
            let app = row["app"] as? String ?? "", id = row["id"] as? String ?? ""
            return NSWorkspace.shared.runningApplications
                .filter { $0.bundleIdentifier != me && $0.activationPolicy == .regular && ($0.localizedName ?? "").localizedCaseInsensitiveContains(app) }
                .map { (id, $0.localizedName ?? app, $0.processIdentifier, row["labels"] as? [String] ?? []) }
        }
        guard !jobs.isEmpty else { return }
        busy = true
        q.async { [weak self] in
            let pressed = jobs.compactMap { job in AutoPress.press(job.2, labels: job.3).map { (job.0, job.1, $0) } }
            DispatchQueue.main.async { self?.busy = false; pressed.forEach { self?.pressed($0.0, app: $0.1, label: $0.2) } }
        }
    }

    private func pressed(_ id: String, app: String, label: String) {
        let line = (try? JSONSerialization.data(withJSONObject: ["id": id, "app": app, "label": label, "at": Date().timeIntervalSince1970])) ?? Data()
        let log = folder + "/watches-log.jsonl"
        if !FileManager.default.fileExists(atPath: log) { FileManager.default.createFile(atPath: log, contents: nil, attributes: [.posixPermissions: 0o600]) }
        if let h = FileHandle(forWritingAtPath: log) { h.seekToEndOfFile(); h.write(line + Data("\n".utf8)); try? h.close() }
        unsaid[id, default: 0] += 1
        guard Date().timeIntervalSince(noticed[id] ?? .distantPast) >= 60 else { return }
        let times = unsaid[id] ?? 1; noticed[id] = Date(); unsaid[id] = 0
        let p = py(["--agent-notify", "Clicked “\(label)” in \(app)" + (times > 1 ? " (\(times) times)" : "") + ". Say “stop watching” to stop."])
        p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice; try? p.run()
    }

    // The first enabled button titled (or described) as one of the labels, in the app's windows and sheets; pressed, its label.
    // Bounded: 25 levels, 3000 elements, 0.4 s per AX call, so a busy app costs a moment, never a hang.
    static func press(_ pid: pid_t, labels: [String]) -> String? {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, 0.4)
        guard let windows = attribute(app, kAXWindowsAttribute) as? [AXUIElement], !windows.isEmpty else { return nil }
        let wanted = Set(labels.map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() })
        var queue = windows.map { ($0, 0) }, next = 0
        while next < queue.count, next < 3000 {
            let (e, depth) = queue[next]; next += 1
            if attribute(e, kAXRoleAttribute) as? String == kAXButtonRole as String, let hit = name(e).first(where: wanted.contains),
               attribute(e, kAXEnabledAttribute) as? Bool != false,
               [.success, .failure, .cannotComplete].contains(AXUIElementPerformAction(e, kAXPressAction as CFString)) {
                return hit   // the press went out: a dialog closing under it can report failure, so never press it twice
            }
            guard depth < 25, let kids = attribute(e, kAXChildrenAttribute) as? [AXUIElement] else { continue }
            queue += kids.map { ($0, depth + 1) }
        }
        return nil
    }

    // A button's names: its title and description, else the text inside it (web buttons often carry their label as a child).
    static func name(_ e: AXUIElement) -> [String] {
        var names = [kAXTitleAttribute, kAXDescriptionAttribute].compactMap { attribute(e, $0) as? String }
        if names.allSatisfy({ $0.isEmpty }), let kids = attribute(e, kAXChildrenAttribute) as? [AXUIElement] {
            names += kids.prefix(3).compactMap { attribute($0, kAXValueAttribute) as? String ?? attribute($0, kAXTitleAttribute) as? String }
        }
        return names.map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }.filter { !$0.isEmpty }
    }

    static func attribute(_ e: AXUIElement, _ key: String) -> CFTypeRef? {
        var value: CFTypeRef?
        return AXUIElementCopyAttributeValue(e, key as CFString, &value) == .success ? value : nil
    }
}
