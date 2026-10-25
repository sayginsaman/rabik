// Updates from the git checkout (not in release builds). Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// Updates: build.sh records the source folder (a git clone); Rabik pulls and rebuilds itself from it, then
// restarts once idle. Local edits or a failed build leave the running version alone.
enum Updater {
    static let src = Bundle.main.object(forInfoDictionaryKey: "RabikSource") as? String ?? ""
    static let managedByNix = src.hasPrefix("/nix/store/")
    static var status = "", checking = false
    static func sh(_ script: String) -> (code: Int32, out: String) {
        let p = Process(), o = Pipe()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh"); p.arguments = ["-c", script, src]; p.standardOutput = o; p.standardError = o
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"; env["RABIK_NO_RESTART"] = "1"; p.environment = env
        let data = runToEnd(p, o)
        return (p.terminationStatus, String(data: data, encoding: .utf8) ?? "")
    }
    static let version: String = {
        if managedByNix { return (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Unknown") + " · Nix" }
        return sh(#"cd "$0" 2>/dev/null && git log -1 --format='%h · %cd' --date=format:'%b %-d, %Y'"#).out.trimmingCharacters(in: .whitespacesAndNewlines)
    }()
    static func check(_ done: @escaping () -> Void = {}) {
        if managedByNix { status = "Run nix profile upgrade or nix run again."; done(); return }
        if src.isEmpty || ProcessInfo.processInfo.environment["RABIK_DIR"] != nil { status = "Preview build"; done(); return }
        guard !checking else { done(); return }
        checking = true
        status = "Checking…"; done()
        DispatchQueue.global().async {
            let r = sh(#"""
                cd "$0" 2>/dev/null || exit 3
                [ -z "$(git status --porcelain)" ] || exit 5
                git fetch -q 2>/dev/null || exit 4
                git merge-base --is-ancestor '@{u}' HEAD 2>/dev/null && exit 0   # level or ahead (unpushed local commits): nothing to pull, no rebuild loop
                git pull -q --ff-only 2>/dev/null || exit 5
                ./build.sh >/dev/null 2>&1 || exit 6
                exit 10
                """#)
            DispatchQueue.main.async {
                checking = false
                status = [0: "Up to date", 3: "Source folder not found (reinstall with build.sh)", 4: "Couldn’t reach GitHub",
                          5: "Skipped: the source folder has local changes", 6: "Update downloaded, but the build failed",
                          10: "Updated. Restarting when you’re not using it…"][r.code] ?? "Update failed"
                done()
                if r.code == 10 { restartWhenIdle() }
            }
        }
    }
    static func restartWhenIdle() {
        if app.busy || agentsUI.hasLive || app.engine.isRunning || app.voice?.isRunning == true || meeting.panel != nil || settings.win?.isKeyWindow == true || onboarding.win != nil {
            DispatchQueue.main.asyncAfter(deadline: .now() + 30) { restartWhenIdle() }
        } else { relaunchSoon() }
    }
    static func schedule() {   // a minute after launch, then every 6 hours
        if managedByNix { status = "Run nix profile upgrade or nix run again."; return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 60) { if Prefs.bool("autoUpdate") { check() } }
        Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { _ in if Prefs.bool("autoUpdate") { check() } }
    }
}
