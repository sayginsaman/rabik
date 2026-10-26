// Updates for a release. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa
#if canImport(Sparkle)
import Sparkle

// A release from the disk image updates through Sparkle: it reads the appcast on GitHub, shows its own update window and installs a
// disk image only when its EdDSA signature matches the key in Info.plist. Settings → Update automatically turns its checks on and
// off. A build from source has no Sparkle and keeps the git updater (Updater).
enum ReleaseUpdates {
    static let controller: SPUStandardUpdaterController? = Bundle.main.object(forInfoDictionaryKey: "SUFeedURL") == nil ? nil
        : SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
    static var available: Bool { controller != nil }
    static func check() { controller?.checkForUpdates(nil) }
    static func automatic(_ on: Bool) { controller?.updater.automaticallyChecksForUpdates = on; controller?.updater.automaticallyDownloadsUpdates = on }
}
#else
enum ReleaseUpdates {   // built without Sparkle (from source, and the checks)
    static let available = false
    static func check() {}
    static func automatic(_ on: Bool) {}
}
#endif
