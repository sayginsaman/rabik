// The selected text and the text cursor in the user's app. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

struct TextSelection {
    let element: AXUIElement, focus: AXUIElement, app: NSRunningApplication, text: String, range: CFRange?
    enum Delivery { case landed, unchanged, unknown }
    static let settle: TimeInterval = 0.05
    static func string(_ value: CFTypeRef?) -> String? {
        value as? String ?? (value as? NSAttributedString)?.string
    }
    static func parent(_ element: AXUIElement) -> AXUIElement? {
        guard let value = axAttribute(element, kAXParentAttribute), CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return (value as! AXUIElement)
    }
    static func capture(_ app: NSRunningApplication? = NSWorkspace.shared.frontmostApplication, enabled: Bool = Prefs.bool("selection"), allowEmpty: Bool = false, keyboardFallback: Bool = false, onSecure: (() -> Void)? = nil) -> TextSelection? {
        guard enabled, AXIsProcessTrusted(), let app,
              app != .current else { return nil }
        let target = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetMessagingTimeout(target, 0.15)
        var secure = false
        func focusedSelection() -> TextSelection? {
            guard let focused = axAttribute(target, kAXFocusedUIElementAttribute) else { return nil }
            let focus = focused as! AXUIElement
            var element: AXUIElement? = focus
            for _ in 0..<16 {
                guard let candidate = element else { break }
                AXUIElementSetMessagingTimeout(candidate, 0.15)
                if axAttribute(candidate, kAXSubroleAttribute) as? String == kAXSecureTextFieldSubrole { secure = true; onSecure?(); return nil }
                let range = selectedRange(candidate), value = string(axAttribute(candidate, kAXValueAttribute))
                let derived = range.flatMap { r -> String? in
                    guard let value, r.location >= 0, r.length >= 0, r.location + r.length <= (value as NSString).length else { return nil }
                    return (value as NSString).substring(with: NSRange(location: r.location, length: r.length))
                }
                if let text = string(axAttribute(candidate, kAXSelectedTextAttribute)) ?? derived ?? (allowEmpty && range != nil ? "" : nil),
                   allowEmpty || text.count <= 6000 {
                    let selection = TextSelection(element: candidate, focus: focus, app: app, text: text, range: range)
                    // nothing highlighted: keep it only as a cursor in a text box, where a draft can go
                    if !text.isEmpty && !allowEmpty || range != nil && (selection.editable || selection.pastable) { return selection }
                }
                guard let next = parent(candidate) else { break }
                element = next
            }
            return nil
        }
        if let selection = focusedSelection() { return selection }
        guard !secure else { return nil }
        for key in ["AXManualAccessibility"] {   // not AXEnhancedUserInterface: it makes Chrome and Electron window moves animate and lag
            if let value = axAttribute(target, key), CFEqual(value, kCFBooleanTrue) { continue }
            _ = AXUIElementSetAttributeValue(target, key as CFString, kCFBooleanTrue)
        }
        if let selection = focusedSelection() { return selection }
        guard !secure, keyboardFallback, NSWorkspace.shared.frontmostApplication == app else { return nil }
        return TextSelection(element: target, focus: target, app: app, text: "", range: nil)
    }
    var caret: Bool { text.isEmpty && range?.length == 0 }
    static func selectedRange(_ element: AXUIElement) -> CFRange? {
        guard let value = axAttribute(element, kAXSelectedTextRangeAttribute), CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
        var range = CFRange()
        return AXValueGetValue(value as! AXValue, .cfRange, &range) ? range : nil
    }
    var editable: Bool {
        var settable = DarwinBoolean(false)
        return range != nil && AXUIElementIsAttributeSettable(element, kAXSelectedTextAttribute as CFString, &settable) == .success && settable.boolValue
    }
    var keyboardOnly: Bool { range == nil && text.isEmpty && CFEqual(element, focus) }
    // Chrome, Electron and web editors often refuse an AX write; a text field there still takes a paste.
    var pastable: Bool {
        keyboardOnly || ["AXTextArea", "AXTextField", "AXComboBox", "AXSearchField", "AXWebArea"].contains {
            $0 == axAttribute(element, kAXRoleAttribute) as? String || $0 == axAttribute(focus, kAXRoleAttribute) as? String
        }
    }
    func apply(_ draft: String, preserveFocus: Bool = false, valid: @escaping () -> Bool, done: @escaping (Bool) -> Void) {
        guard valid() else { done(false); return }
        let before = value
        func confirm(until deadline: Date, _ finished: @escaping (Delivery) -> Void) {
            let result = delivery(draft, before)
            if case .landed = result { finished(result); return }
            guard Date() < deadline, valid() else { finished(result); return }
            DispatchQueue.main.asyncAfter(deadline: .now() + Self.settle) { confirm(until: deadline, finished) }
        }
        func paste(_ attempt: Int = 0) {
            guard pastable, !app.isTerminated, range != nil || keyboardOnly else { done(false); return }
            let target = AXUIElementCreateApplication(app.processIdentifier)
            AXUIElementSetMessagingTimeout(target, 0.15)
            func focusMatches() -> Bool {
                if keyboardOnly { return true }
                guard let focused = axAttribute(target, kAXFocusedUIElementAttribute) else { return false }
                return CFEqual(focused, focus)
            }
            guard valid(), !app.isTerminated, NSWorkspace.shared.frontmostApplication == app,
                  !keyboardOnly || !IsSecureEventInputEnabled(),   // an app-wide keyboard target cannot see a password box: secure input on anywhere = no paste
                  focusMatches(),
                  keyboardOnly || selectionMatches(),
                  pastable,
                  focusMatches(),
                  NSWorkspace.shared.frontmostApplication == app else { done(false); return }
            guard let down = CGEvent(keyboardEventSource: nil, virtualKey: draft.isEmpty ? 51 : 9, keyDown: true),
                  let up = CGEvent(keyboardEventSource: nil, virtualKey: draft.isEmpty ? 51 : 9, keyDown: false) else { done(false); return }
            // One clipboard borrower at a time across Rabik processes; while a hands helper pastes, check again shortly.
            let clipboard = draft.isEmpty ? nil : try? Hands.lease("clipboard.lock", wait: false)
            if !draft.isEmpty && clipboard == nil {
                if attempt < 40 { DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { paste(attempt + 1) } } else { done(false) }
                return
            }
            let restore = draft.isEmpty ? nil : borrowPasteboard(draft)
            let release = { if let clipboard { Hands.unlock(clipboard) } }
            guard draft.isEmpty || restore != nil else { release(); done(false); return }
            let finish = { (ok: Bool) in restore?(); release(); done(ok) }
            // The box is a non-activating panel: while it holds the keyboard, a system ⌘V lands in its own field, not the target.
            for e in [down, up] { e.flags = draft.isEmpty ? [] : .maskCommand; if NSApp.keyWindow == nil { e.post(tap: .cghidEventTap) } else { e.postToPid(app.processIdentifier) } }
            // Posted after every check passed: it went in. Web and Electron fields often read back empty or stale, so the
            // read-back only decides when the clipboard can come back, never whether the paste failed.
            confirm(until: Date().addingTimeInterval(0.45)) { _ in finish(true) }
        }
        let fallback = {
            if preserveFocus { paste() }
            else {   // Rabik may be front (the user clicked its box): wait up to 1 s for the target app to come back
                app.activate()
                func ready(_ tries: Int) { NSWorkspace.shared.frontmostApplication == app || tries >= 20 ? paste() : DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { ready(tries + 1) } }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { ready(0) }
            }
        }
        // A successful AX call can update slowly. Retry only after proving it changed nothing; an unverifiable retry can insert twice.
        guard editable, before != nil, replace(draft) else { fallback(); return }
        confirm(until: Date().addingTimeInterval(0.45)) { result in
            switch result {
            case .landed, .unknown: done(true)   // the write succeeded and the field changed; an odd read-back is no failure
            case .unchanged: valid() ? fallback() : done(false)
            }
        }
    }
    var value: String? { Self.string(axAttribute(element, kAXValueAttribute)) }
    func selectionMatches() -> Bool {
        guard let range, let current = Self.selectedRange(element),
              current.location == range.location, current.length == range.length else { return false }
        if let selected = Self.string(axAttribute(element, kAXSelectedTextAttribute)) { return selected == text }
        guard let value, range.location >= 0, range.length >= 0, range.location + range.length <= (value as NSString).length else { return true }
        return (value as NSString).substring(with: NSRange(location: range.location, length: range.length)) == text
    }
    func landed(_ draft: String, _ before: String?) -> Bool {
        guard let before, let now = value, let range else { return false }
        let source = before as NSString
        guard range.location >= 0, range.length >= 0, range.location + range.length <= source.length else { return false }
        return now == source.replacingCharacters(in:NSRange(location:range.location,length:range.length),with:draft)
    }
    func delivery(_ draft: String, _ before: String?) -> Delivery {
        if landed(draft, before) { return .landed }
        guard let range, let current = Self.selectedRange(element) else { return .unknown }
        let expected = range.location + (draft as NSString).length
        if current.location == expected && current.length == 0 { return .landed }
        return value == before && current.location == range.location && current.length == range.length ? .unchanged : .unknown
    }
    func replace(_ draft: String) -> Bool {
        guard !app.isTerminated, selectionMatches() else { return false }
        // Set only the saved selection; never paste into whichever app happens to be focused.
        return AXUIElementSetAttributeValue(element, kAXSelectedTextAttribute as CFString, draft as CFString) == .success
    }
}
