// Focus nudges and meeting briefs. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa
import EventKit
import UserNotifications

// A Rabik notification (osascript's would open Script Editor on a click). info goes to Recap's delegate, which opens it.
func postNotice(_ id: String, title: String, body: String, info: [String: String] = [:]) {
    let content = UNMutableNotificationContent()
    content.title = title; content.body = body; content.userInfo = info; content.sound = .default
    let center = UNUserNotificationCenter.current()
    center.getNotificationSettings { settings in
        let add = { center.add(UNNotificationRequest(identifier: id, content: content, trigger: nil)) }
        if settings.authorizationStatus == .notDetermined { center.requestAuthorization(options: [.alert, .sound]) { ok, _ in if ok { add() } } }
        else { add() }
    }
}

// Settings → Focus nudges: on a distracting site or app (YouTube, Reddit, X, …) for 5 minutes straight while the user has a goal,
// one gentle line names the goal (brain/goals.py focus_nudge keeps it to 3 a day, 45 minutes apart). Never in a meeting, while
// paused, or in a call app; the window title is read only for browsers, only to name the site, and never stored.
final class FocusNudge {
    static let sites: [(String, String)] = [("youtube", "YouTube"), ("netflix", "Netflix"), ("twitch", "Twitch"), ("tiktok", "TikTok"),
        ("instagram", "Instagram"), ("facebook", "Facebook"), ("reddit", "Reddit"), ("twitter", "X"), ("x.com", "X"), ("9gag", "9GAG"),
        ("prime video", "Prime Video"), ("disney+", "Disney+"), ("hulu", "Hulu")]
    static let browsers = ["Safari", "Google Chrome", "Arc", "Firefox", "Brave Browser", "Microsoft Edge", "Opera", "Vivaldi", "Orion", "Zen", "Dia"]
    private var since: Date?, label = "", nudgedThisStretch = false, timer: Timer?

    // The distraction's name, from the app's name and (for a browser) its window title; nil for work.
    static func distraction(app: String, title: String) -> String? {
        let words = (browsers.contains(app) ? title : app).lowercased()
        if browsers.contains(app), title.hasSuffix(" / X") { return "X" }
        return sites.first { words.contains($0.0) }?.1
    }

    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in self?.tick() }
    }

    private func tick() {
        guard Prefs.bool("focusNudges"), !Prefs.bool("paused"), !meeting.running, callAppsOnMic().isEmpty,
              let front = NSWorkspace.shared.frontmostApplication, front.bundleIdentifier != Bundle.main.bundleIdentifier else { since = nil; return }
        let name = front.localizedName ?? ""
        var title = ""
        if FocusNudge.browsers.contains(name), AXIsProcessTrusted() {
            let ax = AXUIElementCreateApplication(front.processIdentifier)
            AXUIElementSetMessagingTimeout(ax, 0.3)
            if let window = AutoPress.attribute(ax, kAXFocusedWindowAttribute) { title = AutoPress.attribute(window as! AXUIElement, kAXTitleAttribute) as? String ?? "" }
        }
        guard let now = FocusNudge.distraction(app: name, title: title) else { since = nil; return }
        if now != label || since == nil { label = now; since = Date(); nudgedThisStretch = false; return }
        let minutes = Int(Date().timeIntervalSince(since!) / 60)
        guard minutes >= 5, !nudgedThisStretch else { return }
        nudgedThisStretch = true
        DispatchQueue.global().async { [label] in
            let p = py(["--focus-nudge", label, String(minutes)]), out = Pipe(); p.standardOutput = out; p.standardError = FileHandle.nullDevice
            guard let reply = (try? JSONSerialization.jsonObject(with: runToEnd(p, out))) as? [String: Any], let text = reply["text"] as? String else { return }
            postNotice("focus.\(Date().timeIntervalSince1970)", title: "Rabik", body: text)
        }
    }
}

// Settings → Meeting briefs: about five minutes before a calendar meeting with other people, what Rabik knows about them and the
// last meeting with them (brain/brief.py), as a notification; a click shows it in the box and reads it aloud. Once per meeting.
final class MeetingBriefs {
    private var asked = Set<String>(), timer: Timer?

    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.check() }
    }

    func check() {
        guard Prefs.bool("meetingBriefs"), !Prefs.bool("paused"), EKEventStore.authorizationStatus(for: .event) == .fullAccess else { return }
        let now = Date()
        let soon = calendar.events(matching: calendar.predicateForEvents(withStart: now.addingTimeInterval(60), end: now.addingTimeInterval(6 * 60), calendars: nil))
        for e in soon where !e.isAllDay && e.status != .canceled && e.startDate > now.addingTimeInterval(60) {
            let others = (e.attendees ?? []).filter { !$0.isCurrentUser }
            guard !others.isEmpty, !(e.attendees ?? []).contains(where: { $0.isCurrentUser && $0.participantStatus == .declined }) else { continue }
            let key = "\(e.eventIdentifier ?? "")@\(Int(e.startDate.timeIntervalSince1970))"
            guard !asked.contains(key) else { continue }
            asked.insert(key)
            let attendees = others.map { ["name": $0.name ?? "", "email": $0.url.absoluteString.replacingOccurrences(of: "mailto:", with: "")] }
            let event: [String: Any] = ["id": e.eventIdentifier ?? key, "start": Int(e.startDate.timeIntervalSince1970), "title": e.title ?? "", "attendees": attendees]
            let minutes = max(1, Int((e.startDate.timeIntervalSince(now) / 60).rounded()))
            DispatchQueue.global().async {
                guard let data = try? JSONSerialization.data(withJSONObject: event) else { return }
                let p = py(["--brief"]), out = Pipe(), inp = Pipe(); p.standardOutput = out; p.standardInput = inp; p.standardError = FileHandle.nullDevice
                try? p.run(); try? inp.fileHandleForWriting.write(contentsOf: data); try? inp.fileHandleForWriting.close()
                let reply = out.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
                guard let brief = (try? JSONSerialization.jsonObject(with: reply)) as? [String: Any], let text = brief["text"] as? String, !text.isEmpty else { return }
                let title = brief["title"] as? String ?? "Meeting"
                postNotice("brief.\(key)", title: "Before “\(title)” · in \(minutes) min", body: text, info: ["brief": text, "briefTitle": title])
            }
        }
    }

    // A click on the notification: the brief in the box, read aloud like an answer.
    static func show(_ title: String, _ text: String) {
        app.show(); app.pinned = true; app.js("listen"); app.js("words", "Brief: " + title)
        app.answer = "✓ " + text; app.js("line", app.answer); app.deliver(text)
    }
}
