// Settings shared with the brain (settings.json), behind a lock. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// Settings, shared with rabik.py (model, screen, openOn, instant): ~/.config/rabik/settings.json
enum Prefs {
    static let path = (ProcessInfo.processInfo.environment["RABIK_DIR"] ?? NSString(string: "~/.config/rabik").expandingTildeInPath) + "/settings.json"
    static let defaults: [String: Any] = ["hotkeyCode": 49, "hotkeyMods": controlKey | optionKey, "hotkeyLabel": "⌃⌥Space", "login": true, "paused": false, "corner": "top-left", "linger": "normal",
        "soundStart": "Pop", "soundRelease": "Bottle", "soundDone": "Glass", "soundStop": "Tink", "volume": 0.16, "client": "claude", "model": "haiku", "instant": true,
        "microphone": "automatic", "quietAudio": false, "quietLevel": 0.18, "agentModel": "sonnet", "agentUserTools": true, "fixSetup": false,
        "meetingStyle": "Direct", "meetingCustom": "", "meetingStyles": [
            ["name": "Direct", "text": "Lead with the answer in plain words. No hedging or filler."],
            ["name": "Persuasive", "text": "Speak to feelings first: why it matters to them and what it means for them, a vivid picture or short story, then the fact that backs it."],
            ["name": "Technical", "text": "Precise terms, numbers and how it works. Name the tradeoff."],
            ["name": "Friendly", "text": "Warm and conversational, like talking to a colleague. Simple words."]],
        "selection": true, "ahead": true, "aheadDelay": 0.7, "live": true, "screen": "auto", "openOn": "here", "workIn": "back", "miniScreen": true, "draw": true, "guideSteps": "auto", "pageJS": false,
        "speak": false, "showAnswers": "stream", "autoCopy": false, "hideWhenSharing": true, "menuIcon": true, "autoUpdate": true,
        "learn": true, "safe": true, "pointer": false, "meeting": false, "meetingSave": true, "meetingAuto": "sure", "meetingNudge": false, "meetingDetect": true, "learnMe": true, "stats": true, "tips": true, "askMe": true, "meetingSummary": true, "input": "voice", "talkMode": "hold", "speechModel": "speech", "improve": false, "improveAsked": false, "draftInsert": "ask",
        "dictateHotkeyCode": -1, "dictateHotkeyMods": 0, "dictateHotkeyLabel": "", "dictateMode": "cleanup", "dictateHistory": true, "dictateLearn": true, "dictateWords": [], "dictateFixes": [String: String](), "boxW": 500, "boxH": 420]
    static let retiredKeys = ["quietAudio", "quietLevel", "autoCopy", "askMe", "corner", "linger", "soundStart", "soundRelease", "soundDone", "soundStop",
        "instant", "live", "ahead", "aheadDelay", "learn", "selection", "guideSteps", "workIn", "openOn", "miniScreen", "draftInsert",
        "meetingNudge", "meetingDetect", "meetingAuto", "fixSetup", "dictateLearn"]
    // Read from any queue (permission probes in Settings and setup, the speech queue), written on main: every access takes the lock,
    // so a reader gets a whole copy and never sees the dictionary mid-write.
    private static let lock = NSLock()
    static var d: [String: Any] {
        get { lock.lock(); defer { lock.unlock() }; return values }
        set { lock.lock(); values = newValue; lock.unlock() }
    }
    private static var values: [String: Any] = {
        let saved = (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: path)))) as? [String: Any] ?? [:]
        var values = defaults.merging(saved) { $1 }
        if !["cheapest", "balanced", "capable"].contains(values["routing"] as? String ?? "") {
            values["routing"] = values["model"] as? String != "haiku" ? "capable" :
                (values["escalate"] as? Bool != false && values["escalateAuto"] as? Bool != false ? "balanced" : "cheapest")
        }
        for (k, old) in [("boxW", 460.0), ("boxH", 360.0)] where (values[k] as? NSNumber)?.doubleValue == old { values[k] = defaults[k] }   // every write saves the defaults too: the old size untouched is no choice
        // No dictation shortcut, never cleared on purpose: fn alone (code -2, rabikFnKey), unless the talk shortcut already holds fn.
        if values["dictateHotkeyLabel"] as? String == "", values["dictateHotkeyOff"] as? Bool != true, (values["hotkeyMods"] as? Int ?? 0) & (1 << 20) == 0 {
            values["dictateHotkeyCode"] = -2; values["dictateHotkeyMods"] = 1 << 20; values["dictateHotkeyLabel"] = "fn"
        }
        return values   // persisted with the next preference write; legacy keys remain readable
    }()
    @discardableResult static func set(_ k: String, _ v: Any) -> Bool {   // false: not on disk, so the old value stays too
        let old = d[k]; d[k] = v
        do {
            try FileManager.default.createDirectory(atPath: (path as NSString).deletingLastPathComponent, withIntermediateDirectories: true)
            try JSONSerialization.data(withJSONObject: d, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: path), options: .atomic)
        } catch { d[k] = old; return false }
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path)
        return true
    }
    static func bool(_ k: String) -> Bool { d[k] as? Bool ?? false }
    static func str(_ k: String) -> String { d[k] as? String ?? "" }
    static func num(_ k: String) -> Double { (d[k] as? NSNumber)?.doubleValue ?? 0 }
}
