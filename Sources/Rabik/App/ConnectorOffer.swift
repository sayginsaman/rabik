// Connector offers. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa

// Settings → Agents → Offer connectors (on): bringing Notion, Slack, Linear, Figma, Asana or ClickUp to the front while its Claude
// connector isn't connected shows one small card in the box saying what Rabik would read: Connect opens Claude's connectors page,
// Not now waits a week, Don't ask again stops it for that app. Never during a call, an ask, dictation or another card; each app
// at most once a launch, and the connected list is read at most every 6 hours.
final class ConnectorOffer {
    static let apps: [String: (name: String, reads: String)] = [
        "notion.id": ("Notion", "search and read your pages and databases"),
        "com.tinyspeck.slackmacgap": ("Slack", "search and read your channels and messages"),
        "com.linear": ("Linear", "read your issues and projects"),
        "com.figma.Desktop": ("Figma", "read your files and comments"),
        "com.electron.asana": ("Asana", "read your tasks and projects"),
        "com.clickup.desktop-app": ("ClickUp", "read your tasks and docs"),
    ]
    private var connected: [String] = [], checked = Date.distantPast, offered: Set<String> = [], observer: NSObjectProtocol?

    func start() {
        guard observer == nil else { return }
        observer = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] n in
            guard let bundle = (n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication)?.bundleIdentifier else { return }
            self?.consider(bundle)
        }
    }

    static func wanted(_ bundle: String, now: Date = Date()) -> Bool {
        Prefs.bool("connectorOffers") && Prefs.str("client") == "claude" && apps[bundle] != nil
            && !(Prefs.d["connectorMuted"] as? [String] ?? []).contains(bundle)
            && now.timeIntervalSince1970 >= ((Prefs.d["connectorSnooze"] as? [String: Double])?[bundle] ?? 0)
    }

    private var quiet: Bool { meeting.panel != nil || app.busy || app.engine.isRunning || app.dictating || app.panel.isVisible || !callAppsOnMic().isEmpty }

    func consider(_ bundle: String) {
        guard !offered.contains(bundle), ConnectorOffer.wanted(bundle), !quiet, let offer = ConnectorOffer.apps[bundle] else { return }
        let show = { [weak self] in
            guard let self, !self.connected.contains(where: { $0.localizedCaseInsensitiveContains(offer.name) }), !self.quiet,
                  NSWorkspace.shared.frontmostApplication?.bundleIdentifier == bundle else { return }
            offered.insert(bundle)
            app.show(); app.pinned = true; app.agentCard = "connector"
            app.js("connectorOffer", ["app": bundle, "name": offer.name, "reads": offer.reads])
        }
        if Date().timeIntervalSince(checked) < 6 * 3600 { return show() }
        Onboarding.connectors { [weak self] c in self?.connected = c["connected"] as? [String] ?? []; self?.checked = Date(); show() }
    }

    func answer(_ choice: String, _ bundle: String) {   // the card's buttons
        app.agentCard = ""; app.pinned = false; app.defaultKey(false)
        switch choice {
        case "connect": checked = .distantPast; onboarding.grant("connectors")
        case "later": var snooze = Prefs.d["connectorSnooze"] as? [String: Double] ?? [:]; snooze[bundle] = Date().addingTimeInterval(7 * 86400).timeIntervalSince1970; Prefs.set("connectorSnooze", snooze)
        case "never": Prefs.set("connectorMuted", Array(Set((Prefs.d["connectorMuted"] as? [String] ?? []) + [bundle])).sorted())
        default: break
        }
        app.hide(after: choice == "connect" ? 0.5 : 0.3)
    }
}
