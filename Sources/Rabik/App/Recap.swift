// The daily recap. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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


import UserNotifications

// The daily recap (brain/recap.py). Its launchd job's queue entry, Rabik starting and the Mac waking each ask the brain whether the
// evening recap is due; the brain makes it at most once a day, and only a day with something in it. Rabik posts its own notification
// (a click opens the card; osascript's would open Script Editor), or, with notifications off, shows the card once the box is free.
final class Recap: NSObject, UNUserNotificationCenterDelegate {
    var checking = false, waiting: [String: Any]?
    override init() {
        super.init()
        UNUserNotificationCenter.current().delegate = self
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in self?.catchUp() }
    }
    func brain(_ args: [String], _ done: @escaping ([String: Any]) -> Void) {   // one --recap command off the main thread; its JSON back on it
        DispatchQueue.global().async {
            let p = py(["--recap"] + args), out = Pipe(); p.standardOutput = out; p.standardError = FileHandle.nullDevice
            let value = (try? JSONSerialization.jsonObject(with: runToEnd(p, out))) as? [String: Any] ?? [:]
            DispatchQueue.main.async { done(value) }
        }
    }
    func catchUp() {
        guard !checking else { return }
        checking = true
        brain(["catch-up"]) { [weak self] made in
            guard let self else { return }
            checking = false
            if made["day"] != nil && made["empty"] == nil { ready(made) }
        }
    }
    func sync() { brain(["schedule"]) { [weak self] _ in self?.catchUp() } }   // Settings changed it: the job follows, and one already due shows now
    func ready(_ recap: [String: Any]) {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            DispatchQueue.main.async { [self] in
                switch settings.authorizationStatus {
                case .notDetermined:   // asked with the first recap, not at setup
                    center.requestAuthorization(options: [.alert, .sound]) { ok, _ in DispatchQueue.main.async { ok ? self.post(recap) : self.showWhenFree(recap) } }
                case .authorized, .provisional, .ephemeral: post(recap)
                default: showWhenFree(recap)
                }
            }
        }
    }
    func post(_ recap: [String: Any]) {
        let day = recap["day"] as? String ?? "", content = UNMutableNotificationContent()
        content.title = "Your day with Rabik"; content.body = recap["headline"] as? String ?? "Your daily recap is ready."
        let open = (recap["actions"] as? [[String: Any]] ?? []).filter { ($0["added"] as? String ?? "").isEmpty }.count
        if open > 0 { content.subtitle = "\(open) to-do\(open == 1 ? "" : "s") to review" }
        content.userInfo = ["recap": day]; content.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "recap." + day, content: content, trigger: nil))
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler done: @escaping () -> Void) {
        let day = response.notification.request.content.userInfo["recap"] as? String ?? ""
        DispatchQueue.main.async { [self] in if !day.isEmpty { open(day) } }
        done()
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])   // Rabik is a menu bar app: it is "frontmost" more often than it looks
    }
    func showWhenFree(_ recap: [String: Any]) {   // no notifications: the card, once the user is not asking or typing
        guard app.busy || app.composing || app.engine.isRunning else { waiting = nil; show(recap); return }
        waiting = recap
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in if let recap = self?.waiting { self?.showWhenFree(recap) } }
    }
    func open(_ day: String) { brain(["read", day]) { [weak self] recap in if recap["day"] != nil { self?.show(recap) } } }   // as saved: added marks show
    func show(_ recap: [String: Any]) { app.show(); app.pinned = true; app.js("recap", recap) }
    // Add to Reminders, from the recap card, a meeting's panel or its page in Settings: Reminders access is asked here, in the app, the
    // first time; the brain adds only what is not added yet and says which items are added now.
    func add(_ source: String, _ keys: [String], _ reply: @escaping ([String: Any]) -> Void) {
        let go = { [self] in
            guard let data = try? JSONSerialization.data(withJSONObject: keys), let list = String(data: data, encoding: .utf8) else { return }
            brain(["remind", source, list]) { reply($0.isEmpty ? ["error": "Reminders did not answer. Try again."] : $0) }
        }
        switch EKEventStore.authorizationStatus(for: .reminder) {
        case .fullAccess: go()
        case .notDetermined: calendar.requestFullAccessToReminders { ok, _ in DispatchQueue.main.async { ok ? go() : reply(["need": "reminders"]) } }
        default: reply(["need": "reminders"])
        }
    }
}
