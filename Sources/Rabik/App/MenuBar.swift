// The app delegate and the menu bar item. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// Opening Rabik again (Spotlight, Finder, Dock) while it runs: setup the first time, Settings after (Agents is the first item there).
final class Delegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        meeting.discard(); app.hush(); app.drawing.clear(); app.quietAudio.end(immediate: true); app.shush()
        MeetingArchive.writes.notify(queue: .main) { sender.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows: Bool) -> Bool {
        UserDefaults.standard.bool(forKey: "onboarded") ? settings.open() : onboarding.open()
        return false
    }
}

// The menu bar icon: quick actions, today's usage.
final class MenuBar: NSObject, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    override init() {
        super.init()
        item.button?.image = MenuBar.logo
        let m = NSMenu(); m.delegate = self; item.menu = m
        item.isVisible = Prefs.bool("menuIcon")
        paint()
    }
    // The Rabik face (docs/rabik-logo.png) as a template: eyes and smile cut out, so the menu bar tints it for light, dark and paused.
    static let logo: NSImage = {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { r in
            let s = r.insetBy(dx: 1.5, dy: 1.5), w = s.width, h = s.height
            NSColor.black.setFill(); NSBezierPath(roundedRect: s, xRadius: w * 0.3, yRadius: h * 0.3).fill()
            NSGraphicsContext.current?.compositingOperation = .destinationOut
            for x in [0.31, 0.69] {
                NSBezierPath(roundedRect: NSRect(x: s.minX + w * (x - 0.055), y: s.minY + h * 0.45, width: w * 0.11, height: h * 0.21), xRadius: w * 0.055, yRadius: w * 0.055).fill()
            }
            let smile = NSBezierPath()
            smile.appendArc(withCenter: NSPoint(x: s.midX, y: s.minY + h * 0.47), radius: w * 0.12, startAngle: 222, endAngle: 318)
            smile.lineWidth = w * 0.085; smile.lineCapStyle = .round; smile.stroke()
            return true
        }
        image.isTemplate = true; image.accessibilityDescription = "Rabik"
        return image
    }()
    func paint() { item.button?.appearsDisabled = Prefs.bool("paused"); item.button?.title = meeting.running ? " ·" : ""; item.length = meeting.running ? 38 : NSStatusItem.squareLength }
    func menuNeedsUpdate(_ m: NSMenu) {
        m.removeAllItems()
        let keys = Prefs.str("hotkeyLabel")
        let hint = Prefs.str("input") == "type" ? "Press \(keys) to type" : Prefs.str("talkMode") == "toggle" ? "Press \(keys) to talk · again to send" : "Hold \(keys) and talk"
        let head = NSMenuItem(title: Prefs.bool("paused") ? "Rabik is paused" : hint, action: nil, keyEquivalent: "")
        head.isEnabled = false; m.addItem(head)
        m.addItem(.separator())
        add(m, "Ask Rabik", #selector(ask), "")
        add(m, "Dictation History…", #selector(dictationHistory), "")
        if pasteHotkeyRegistered && (app.lastDictation ?? DictationData.archive.history.first?.text) != nil {
            add(m, "Paste Last Dictation", #selector(pasteDictation), "v"); m.items.last?.keyEquivalentModifierMask = [.control, .command]
        }
        add(m, agentsUI.count > 0 ? "Agents · \(agentsUI.count) running…" : "Agents…", #selector(openAgents), "")
        if agentsUI.hasLive || agentsUI.lingering { add(m, Prefs.bool("agentsHidden") ? "Show Agent Shelf" : "Hide Agent Shelf", #selector(hideAgents), "") }
        if Prefs.bool("meeting") { add(m, meeting.running ? "Stop Meeting Copilot" : "Meeting Copilot…", #selector(toggleMeeting), "") }
        add(m, Prefs.bool("paused") ? "Resume Rabik" : "Pause Rabik", #selector(pause), "")
        m.addItem(.separator())
        let u = NSMenuItem(title: today(), action: nil, keyEquivalent: ""); u.isEnabled = false; m.addItem(u)
        m.addItem(.separator())
        add(m, "Settings…", #selector(openSettings), ",")
        add(m, "Setup & Permissions…", #selector(openSetup), "")
        add(m, "Report Feedback…", #selector(reportFeedback), "")
        if !Prefs.bool("tips") { add(m, "Show Tips Again", #selector(tipsOn), "") }   // a tip's "Turn off" has no Settings row to undo it
        m.addItem(.separator())
        add(m, "Quit Rabik", #selector(quit), "q")
    }
    func add(_ m: NSMenu, _ t: String, _ a: Selector, _ k: String) { let i = NSMenuItem(title: t, action: a, keyEquivalent: k); i.target = self; m.addItem(i) }
    func today() -> String {
        let format = DateFormatter(); format.dateFormat = "yyyy-MM-dd"; let day = format.string(from: Date())
        let root = (Prefs.path as NSString).deletingLastPathComponent
        let log = (try? String(contentsOfFile: root + "/log.jsonl", encoding: .utf8)) ?? ""
        let rows = log.split(separator: "\n").compactMap { try? JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: Any] }
            .filter { ($0["at"] as? String ?? "").hasPrefix(day) && $0["reply"] != nil }
        let askUSD = rows.reduce(0.0) { $0 + (($1["usd"] as? NSNumber)?.doubleValue ?? 0) }
        let agentUSD = ((try? FileManager.default.contentsOfDirectory(atPath: root + "/agents")) ?? []).reduce(0.0) { total, name in
            guard let data = try? Data(contentsOf: URL(fileURLWithPath: root + "/agents/" + name + "/state.json")),
                  let row = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return total }
            if row["costDay"] as? String == day { return total + ((row["costToday"] as? NSNumber)?.doubleValue ?? 0) }
            guard row["costDay"] == nil, let created = (row["created"] as? NSNumber)?.doubleValue,
                  format.string(from: Date(timeIntervalSince1970: created)) == day else { return total }
            return total + ((row["cost"] as? NSNumber)?.doubleValue ?? 0)   // shortcut: legacy states use creation day; exact daily counters start with this version
        }
        let lower = rows.contains { $0["usd"] is NSNull } ? "≥" : ""
        return "Today: \(lower)\(String(format: "$%.2f", askUSD + agentUSD)) · asks \(String(format: "$%.2f", askUSD)) · agents \(String(format: "$%.2f", agentUSD))"
    }
    @objc func toggleMeeting() { meeting.running ? meeting.stop() : meeting.open() }
    @objc func ask() { if meeting.running { return meeting.focus() }; app.clickTalk = true; app.start(); if !app.engine.isRunning { app.clickTalk = false } }   // the same box as the shortcut, like its mic button
    @objc func pause() { Prefs.set("paused", !Prefs.bool("paused")); if Prefs.bool("paused") { meeting.stop(paused: true); app.close(clear: false); agentsUI.stopAll() }; paint(); settings.push() }
    @objc func openSettings() { settings.open() }
    @objc func dictationHistory() { settings.open(tab: "dictation") }
    @objc func pasteDictation() { DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { app.pasteLastDictation() } }   // after the menu closes and focus returns
    @objc func openAgents() { agentsUI.openView() }
    @objc func hideAgents() { Prefs.set("agentsHidden",!Prefs.bool("agentsHidden")) }
    @objc func openSetup() { onboarding.open() }
    @objc func reportFeedback() { settings.open(tab:"feedback") }
    @objc func tipsOn() { settings.apply("tips", true); settings.push() }
    @objc func quit() { NSApp.terminate(nil) }
}
