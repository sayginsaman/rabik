// The panels the box and its pointer sit in. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// The box can take typing (canBecomeKey) without pulling Rabik forward (nonactivating): the user's app stays in front.
final class KeyPanel: NSPanel { override var canBecomeKey: Bool { true } }

// MARK: - Agent panels
final class ShelfPanel: NSPanel { override var canBecomeKey: Bool { false } }

// WebKit tracks hover only while the app is active, and Rabik never activates for the shelf, so hover reached the page only
// now and then. This view tracks the mouse itself (active always; the owner must be a view) and hands the page page-space points.
final class PointerView: NSView {
    var onPointer: (([Double]) -> Void)?
    override init(frame: NSRect) {
        super.init(frame:frame)
        addTrackingArea(NSTrackingArea(rect:.zero,options:[.mouseMoved,.mouseEnteredAndExited,.activeAlways,.inVisibleRect],owner:self,userInfo:nil))
    }
    required init?(coder: NSCoder) { nil }
    override func mouseMoved(with e: NSEvent) { send(e) }
    override func mouseEntered(with e: NSEvent) { send(e) }
    override func mouseExited(with e: NSEvent) { here() }
    func here() {
        guard let window else { onPointer?([]); return }
        let p = convert(window.convertPoint(fromScreen:NSEvent.mouseLocation),from:nil)
        onPointer?(bounds.contains(p) ? [p.x,bounds.height-p.y] : [])
    }
    func send(_ e: NSEvent) { let p = convert(e.locationInWindow,from:nil); onPointer?([p.x,bounds.height - p.y]) }
}
