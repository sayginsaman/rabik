// Open at login. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa
import ServiceManagement

// Settings → General → Open at login. A release (from the disk image) is a login item through SMAppService and turns itself on
// once, at its first launch; a build from source keeps build.sh's LaunchAgent, which also restarts it after a crash.
enum LoginItem {
    static var fromSource: Bool { Bundle.main.object(forInfoDictionaryKey: "RabikSource") != nil }

    static func firstLaunch() {   // a release's first run: on, as Settings says by default
        guard !fromSource, ProcessInfo.processInfo.environment["RABIK_DIR"] == nil, !UserDefaults.standard.bool(forKey: "loginItemSet") else { return }
        UserDefaults.standard.set(true, forKey: "loginItemSet")
        if Prefs.bool("login") { _ = set(true) }
    }

    // What System Settings → Login Items shows now: the switch follows it if the user changed it there.
    static func current() -> Bool? { fromSource ? nil : SMAppService.mainApp.status == .enabled }

    @discardableResult static func set(_ on: Bool) -> Bool {
        if fromSource {
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            p.arguments = [on ? "enable" : "disable", "gui/\(getuid())/com.rabik.app"]; try? p.run(); return true
        }
        do { if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }; return true }
        catch { return false }
    }
}
