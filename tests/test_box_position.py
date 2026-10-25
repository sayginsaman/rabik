"""Settings → General → Box position: where the box opens and which way it grows; and the menu bar's Rabik face."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.interaction
from tests import native_source, run_swift


class BoxPositionTests(unittest.TestCase):
    def setUp(self):
        self.swift = native_source()

    def test_the_box_opens_top_center_unless_settings_say_otherwise(self):
        defaults = self.swift[self.swift.index('static let defaults'):self.swift.index('static let retiredKeys')]
        self.assertIn('"boxPosition": "top-center"', defaults)
        self.assertNotIn('"corner"', self.swift)   # the old top-left/top-right switch is gone, not a second source of truth
        show = self.swift[self.swift.index('    func show() {'):self.swift.index('    func hide(after')]
        self.assertIn('boxOrigin(panel.frame.size, in: mouseScreen.visibleFrame)', show)

    def test_each_spot_places_the_box_and_keeps_its_side_when_the_width_changes(self):
        helpers = self.swift[self.swift.index('    var boxSpot: String {'):self.swift.index('    func show() {')]
        harness = '''import Cocoa
enum Prefs { static var spot = ""; static func str(_ k: String) -> String { k == "boxPosition" ? spot : "" } }
struct Box {
''' + helpers + '''}
let vf = NSRect(x: 0, y: 25, width: 1440, height: 850), size = NSSize(width: 500, height: 420)
let expected: [String: NSPoint] = ["top-left": NSPoint(x: 14, y: 445), "top-center": NSPoint(x: 470, y: 445), "top-right": NSPoint(x: 926, y: 445),
    "bottom-left": NSPoint(x: 14, y: 35), "bottom-center": NSPoint(x: 470, y: 35), "bottom-right": NSPoint(x: 926, y: 35)]
for (spot, origin) in expected {
    Prefs.spot = spot; let box = Box()
    precondition(box.boxOrigin(size, in: vf) == origin, "\\(spot) opens at \\(box.boxOrigin(size, in: vf))")
    precondition(box.boxAtBottom == spot.hasPrefix("bottom"), spot)
    let wide = NSRect(origin: origin, size: size), pill = box.boxWidth(wide, 36)   // the dictation pill keeps the box's side, or its middle
    precondition(pill.width == 36 && pill.origin.y == origin.y, spot)
    precondition(spot.hasSuffix("left") ? pill.minX == wide.minX : spot.hasSuffix("right") ? pill.maxX == wide.maxX : pill.midX == wide.midX, spot)
}
for odd in ["", "middle", "top-left "] { Prefs.spot = odd; precondition(Box().boxSpot == "top-center", odd) }   // missing or hand-edited: top center
print("box spots ok")
'''
        self.assertIn('box spots ok', run_swift(self, harness))

    def test_the_box_grows_away_from_its_edge(self):
        # A bottom box grows up and its pill sits on the bottom edge; dragging an edge still moves only that edge.
        self.assertIn('if fromBottom || !fromTop && !boxAtBottom { f.origin.y = f.maxY - h }', self.swift)
        self.assertIn('if on { if !boxAtBottom { f.origin.y = f.maxY - w }; f.size.height = w }', self.swift)
        self.assertIn('fromTop = ed.t; fromBottom = ed.b', self.swift)
        follow = self.swift[self.swift.index('    func followPointerScreen()'):self.swift.index('    func startFollowingPointerScreen()')]
        self.assertIn('if !stuck && boxSpot.hasSuffix("center")', follow)   # centred on the next display too, unless the user placed it

    def test_a_new_position_shows_at_once(self):
        self.assertIn('if k == "boxPosition" { app.placeBox() }', self.swift)
        place = self.swift[self.swift.index('    func placeBox()'):self.swift.index('    func followPointerScreen()')]
        self.assertIn('guard panel.isVisible else { show(); hide(after: 1.5); return }', place)
        self.assertIn('guard !stuck, !dragging else { return }', place)   # a box the user dragged stays where they put it

    def test_box_position_can_be_set_by_voice(self):
        self.assertEqual(brain.interaction.picks()['boxPosition'], ('Box position', {
            'Top left': 'top-left', 'Top center': 'top-center', 'Top right': 'top-right',
            'Bottom left': 'bottom-left', 'Bottom center': 'bottom-center', 'Bottom right': 'bottom-right'}))

    def test_the_menu_bar_shows_the_rabik_face_as_a_template(self):
        menu = self.swift[self.swift.index('final class MenuBar'):]
        self.assertIn('item.button?.image = MenuBar.logo', menu)
        self.assertNotIn('waveform', menu)
        logo = menu[menu.index('    static let logo: NSImage = {'):menu.index('    func paint() {')]
        harness = '''import Cocoa
enum MenuBar {
''' + logo + '''}
let image = MenuBar.logo
precondition(image.isTemplate && image.size == NSSize(width: 18, height: 18))
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 36, pixelsHigh: 36, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                           isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
rep.size = NSSize(width: 18, height: 18)
NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
image.draw(in: NSRect(x: 0, y: 0, width: 18, height: 18)); NSGraphicsContext.restoreGraphicsState()
func alpha(_ x: CGFloat, _ y: CGFloat) -> CGFloat { rep.colorAt(x: Int(x * 2), y: 35 - Int(y * 2))!.alphaComponent }   // points, y up
precondition(alpha(9, 14) > 0.9, "the face is solid")
precondition(alpha(6.15, 9.8) < 0.1 && alpha(11.85, 9.8) < 0.1, "the eyes are cut out")
precondition(alpha(9, 6.75) < 0.1, "the smile is cut out")
precondition(alpha(0.5, 0.5) < 0.1, "the corners are round")
print("logo ok")
'''
        self.assertIn('logo ok', run_swift(self, harness))


if __name__ == '__main__':
    unittest.main()
