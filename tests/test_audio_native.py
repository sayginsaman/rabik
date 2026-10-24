"""Audio policy regressions with fake devices and volume; never touches VM audio hardware."""
from pathlib import Path
import sys
import unittest

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "macOS Swift audio regression")
class AudioNativeTests(unittest.TestCase):
    def test_siri_voice_retries_until_the_voice_test_succeeds(self):
        source = (ROOT / "Atticus.swift").read_text()
        voice = source[source.index("var siriVoiceTrying"):source.index("// The talk shortcut")]
        before_test = voice[:voice.index("DispatchQueue.global().async")]
        self.assertNotIn('set(true, forKey: "siriVoice")', before_test)
        self.assertIn('else { UserDefaults.standard.set(true, forKey: "siriVoice") }', voice)
        deliver = source[source.index("    func deliver("):source.index("    func linger(")]
        self.assertIn("siriVoice()", deliver)

    def test_device_choice_falls_back_without_opening_bluetooth(self):
        source = (ROOT / "Atticus.swift").read_text()
        policy = source[source.index("struct MicrophoneDevice"):source.index("func listenMic()")]
        run_swift(self, 
            """import Foundation
import CoreAudio
func audioProp<T>(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector, _ zero: T) -> [T] { [] }
func audioString(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector) -> String? { nil }
"""
            + policy
            + """
let builtIn = MicrophoneDevice(id: 1, uid: "built-in", name: "MacBook Microphone", transport: kAudioDeviceTransportTypeBuiltIn)
let bluetooth = MicrophoneDevice(id: 2, uid: "bluetooth", name: "Headphones", transport: kAudioDeviceTransportTypeBluetooth)
let usb = MicrophoneDevice(id: 3, uid: "usb", name: "Studio Mic", transport: kAudioDeviceTransportTypeUSB)
let devices = [builtIn, bluetooth, usb]
precondition(chooseMic("usb", devices, 2)?.id == 3, "remembered UID was ignored")
precondition(chooseMic("gone", devices, 2)?.id == 1, "missing choice did not use Automatic")
precondition(chooseMic("automatic", devices, 2)?.id == 1, "Automatic selected the Bluetooth input")
precondition(chooseMic("automatic", devices, 3)?.id == 3, "Automatic ignored a non-Bluetooth default")
precondition(chooseMic("automatic", [bluetooth], 2)?.id == 2, "Automatic lost the only available input")
print("microphone policy ok")
"""
        )
        start = source[source.index("    func start()", source.index("final class App")):source.index("    func heard(", source.index("final class App"))]
        self.assertIn("AVCaptureDevice(uniqueID: $0.uid)", start)   # opens only the chosen mic
        self.assertNotIn("AVAudioEngine()", source)   # its input node opens the default (Bluetooth) mic first
        self.assertIn("cfg.microphoneCaptureDeviceID = microphoneID", source)
        self.assertIn("microphoneID: demo ? nil : listenMic()?.uid", source)

    def test_quiet_audio_restores_release_and_cancel(self):
        source = (ROOT / "Atticus.swift").read_text()
        model = source[source.index("struct AudioVolumeSnapshot"):source.index("struct CoreAudioVolume")]
        quiet = source[source.index("final class AudioQuiet"):source.index("enum AudioRecovery")]
        run_swift(self, 
            """import Foundation
"""
            + model
            + quiet
            + """
final class FakeAudio: AudioVolumeLayer {
    var volume: Float32 = 0.8, reads = 0, writes: [Float32] = [], mediaPaused = true, failAt: Int?
    func snapshot() -> AudioVolumeSnapshot? {
        reads += 1
        return AudioVolumeSnapshot(uid: "fixture", selector: 1, volume: volume, owner: 1)
    }
    func set(_ snapshot: AudioVolumeSnapshot, volume: Float32) -> Bool {
        writes.append(volume)
        if writes.count == failAt { return false }
        self.volume = volume; return true
    }
}
let now: (TimeInterval, @escaping () -> Void) -> Void = { _, work in work() }
let offLayer = FakeAudio(), off = AudioQuiet(layer: offLayer, later: now)
off.begin(false)
precondition(offLayer.reads == 0 && offLayer.writes.isEmpty && offLayer.mediaPaused, "setting off changed audio or playback")

let layer = FakeAudio()
var marker: AudioVolumeSnapshot?
let quiet = AudioQuiet(layer: layer, changed: { marker = $0 }, later: now)
quiet.begin(true)
precondition(abs(layer.volume - 0.144) < 0.001 && layer.mediaPaused, "listening did not quiet audio or started paused media")
quiet.end()
precondition(layer.volume == 0.8 && marker == nil, "release did not restore the exact volume")

quiet.begin(true); quiet.end()
precondition(layer.volume == 0.8, "cancel did not restore the exact volume")

quiet.begin(true); layer.failAt = layer.writes.count + 6; quiet.end()
precondition(layer.volume == 0.8 && marker == nil, "a missing output device did not retry the restore")
print("quiet audio policy ok")
"""
        )


if __name__ == "__main__":
    unittest.main()
