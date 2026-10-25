// What Rabik's web views may load. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// Every web view shows one local page (loadPage: an HTML string, so about:blank) and never goes anywhere else. A link, a
// form or a script that tries to navigate is stopped, so nothing loaded later can stand in for Rabik's own UI and talk to
// its message handlers (the Allow card among them). The pages' own forms already prevent their default submit.
final class LocalPageOnly: NSObject, WKNavigationDelegate {
    static let shared = LocalPageOnly()

    static func allows(_ action: WKNavigationAction) -> Bool {
        guard action.navigationType == .other || action.navigationType == .reload else { return false }   // links, forms, history
        let scheme = action.request.url?.scheme?.lowercased()
        return scheme == nil || scheme == "about"   // the page itself (an HTML string): never a site or a file
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        decisionHandler(LocalPageOnly.allows(action) ? .allow : .cancel)
    }
}
