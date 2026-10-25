// Dictation history and the user's spellings, kept on this Mac. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// Text stays local; totals survive history deletion and never contain dictated words.
enum DictationData {
    struct Entry: Codable {
        let id: String, timestamp: Double, app: String, text: String
        let raw: String?
    }
    struct Archive: Codable {
        var history: [Entry] = []
        var words = 0, sessions = 0, todayWords = 0
        var day = ""
        var seconds = 0.0
    }
    static var path: String { (Prefs.path as NSString).deletingLastPathComponent + "/dictation.json" }
    static var archive = (try? JSONDecoder().decode(Archive.self, from: Data(contentsOf: URL(fileURLWithPath: path)))) ?? Archive()
    static var words: [String] { Prefs.d["dictateWords"] as? [String] ?? [] }
    static func day(_ date: Date = Date()) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f.string(from: date)
    }
    static func prune() { archive.history = Array(archive.history.filter { $0.timestamp > Date().timeIntervalSince1970 - 30 * 86400 }.prefix(500)) }
    @discardableResult static func save() -> Bool {
        do {
            let folder = (path as NSString).deletingLastPathComponent
            try FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let data = try JSONEncoder().encode(archive)
            // Set permissions before writing any transcript bytes, including on replacement.
            let tmp = folder + "/.dictation-" + UUID().uuidString
            guard FileManager.default.createFile(atPath: tmp, contents: nil, attributes: [.posixPermissions: 0o600]) else { return false }
            defer { try? FileManager.default.removeItem(atPath: tmp) }
            try data.write(to: URL(fileURLWithPath: tmp))
            guard rename(tmp, path) == 0 else { return false }
            return true
        } catch { return false }
    }
    @discardableResult static func record(_ text: String, raw: String, app: String, seconds: Double) -> Bool {
        let old = archive, count = text.split(whereSeparator: { $0.isWhitespace }).count
        if archive.day != day() { archive.day = day(); archive.todayWords = 0 }
        archive.words += count; archive.todayWords += count; archive.sessions += 1
        archive.seconds += max(0, Double(count) / 40 * 60 - seconds)
        if Prefs.bool("dictateHistory") {
            archive.history.insert(Entry(id: UUID().uuidString, timestamp: Date().timeIntervalSince1970, app: app, text: text, raw: raw == text ? nil : raw), at: 0)
        }
        prune()
        if save() { return true }; archive = old; return false
    }
    static func state() -> [String: Any] {
        let count = archive.history.count
        prune()
        if archive.history.count != count { _ = save() }
        return ["words": words, "history": archive.history.map { e -> [String: Any] in
            var row: [String: Any] = ["id": e.id, "timestamp": e.timestamp, "app": e.app, "text": e.text]
            if let raw = e.raw { row["raw"] = raw }; return row
        }, "stats": ["today": archive.day == day() ? archive.todayWords : 0, "words": archive.words, "sessions": archive.sessions, "minutes": Int(archive.seconds / 60)]]
    }
    @discardableResult static func word(_ value: String, replacing: String? = nil) -> Bool {
        let value = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty, value.count <= 80, !value.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else { return false }
        var list = words.filter { $0 != replacing }
        if !list.contains(value) { guard list.count < 500, list.reduce(0, { $0 + $1.count }) + value.count <= 4000 else { return false }; list.append(value) }
        guard Prefs.set("dictateWords", list) else { return false }
        if let replacing, replacing != value { Prefs.set("dictateFixes", fixes.mapValues { $0 == replacing ? value : $0 }) }
        return true
    }
    @discardableResult static func forget(_ word: String) -> Bool {
        guard Prefs.set("dictateWords", words.filter { $0 != word }) else { return false }
        Prefs.set("dictateFixes", fixes.filter { $0.value != word }); return true
    }
    // Heard spelling (lowercased) → the user's spelling, swapped in whole words before dictation is inserted.
    static var fixes: [String: String] { Prefs.d["dictateFixes"] as? [String: String] ?? [:] }
    static func known(_ word: String) -> Bool { NSSpellChecker.shared.checkSpelling(of: word, startingAt: 0).location == NSNotFound }
    // Every heard form is kept: cleanup gets it as a hint, and one that is no real word is also swapped here.
    @discardableResult static func fix(_ heard: String, _ word: String) -> Bool {
        let key = heard.lowercased()
        guard key != word, words.contains(word), fixes.count < 500 else { return false }
        var list = fixes; list[key] = word
        return Prefs.set("dictateFixes", list)
    }
    // A heard form that is itself real words ("cash" for "cache", "start" for a name) is never swapped blindly: only cleanup, with context, may.
    static func fixed(_ text: String) -> String {
        fixes.reduce(text) { text, fix in
            guard let re = try? NSRegularExpression(pattern: "(?<![\\p{L}\\p{N}])" + NSRegularExpression.escapedPattern(for: fix.key) + "(?![\\p{L}\\p{N}])", options: .caseInsensitive) else { return text }
            let out = NSMutableString(string: text)
            let matches = re.matches(in: text, range: NSRange(location: 0, length: out.length))
            if matches.isEmpty || known(fix.key) { return text }
            for m in matches.reversed() {
                let found = out.substring(with: m.range), value = fix.value
                // A sentence-start capital stays when the learned spelling is lowercase.
                out.replaceCharacters(in: m.range, with: found.first?.isUppercase == true && value.first?.isLowercase == true ? value.prefix(1).uppercased() + value.dropFirst() : value)
            }
            return out as String
        }
    }
    static func distance(_ a: String, _ b: String) -> Int {
        let x = Array(a), y = Array(b)
        var row = Array(0...y.count)
        for (i, c) in x.enumerated() {
            var next = [i + 1]
            for (j, d) in y.enumerated() { next.append(min(next[j] + 1, row[j + 1] + 1, row[j] + (c == d ? 0 : 1))) }
            row = next
        }
        return row[y.count]
    }
    // How a word sounds, roughly: vowels drop and Soundex-like classes merge (t/d, lips b/p/f/v, nasals m/n),
    // so "Saarth", "Sarda" and "sort" become "srt", and "somebody" sits one sound from "some of you".
    // Same rule as dictate_sound in rabik.py.
    static func sound(_ text: String) -> String {
        var s = String(text.lowercased().folding(options: .diacriticInsensitive, locale: nil).filter { $0.isLetter })
        for (a, b) in [("ph", "f"), ("th", "t"), ("ck", "k"), ("sh", "s"), ("qu", "k")] { s = s.replacingOccurrences(of: a, with: b) }
        let merge: [Character: Character] = ["d": "t", "b": "p", "f": "p", "v": "p", "n": "m", "g": "k", "c": "k", "q": "k", "z": "s", "x": "s"]
        var out = ""
        for (i, c) in s.enumerated() {
            let k: Character? = "aeiouyhw".contains(c) ? (i == 0 ? "a" : nil) : merge[c] ?? c
            if let k, out.last != k { out.append(k) }
        }
        return out
    }
    static func sounds(_ a: String, _ b: String) -> Bool {
        let x = sound(a), y = sound(b)
        return x.count >= 2 && x.first == y.first && (x == y || min(x.count, y.count) >= 3 && distance(x, y) <= 1)
    }
    // A fix is one to three dictated words retyped as one word that is spelled or sounds alike ("Sarda", "start to" → "Saarth", "some of you" → "Semva"); a new idea is neither.
    // An everyday lowercase word is no name to learn.
    static func correction(_ original: String, _ edited: String) -> (heard: String, word: String)? {
        var a = original.split(whereSeparator: { $0.isWhitespace }).map(String.init)
        var b = edited.split(whereSeparator: { $0.isWhitespace }).map(String.init)
        while let x = a.first, x == b.first { a.removeFirst(); b.removeFirst() }
        while let x = a.last, x == b.last { a.removeLast(); b.removeLast() }
        guard (1...3).contains(a.count), b.count == 1 else { return nil }
        let trim = CharacterSet.punctuationCharacters
        let old = a.joined(separator: " ").trimmingCharacters(in: trim), new = b[0].trimmingCharacters(in: trim)
        guard old != new, (2...64).contains(new.count), new.unicodeScalars.allSatisfy({ CharacterSet.letters.contains($0) || $0 == "'" || $0 == "-" }) else { return nil }
        let near = a.count == 1 && distance(old.lowercased(), new.lowercased()) <= max(1, max(old.count, new.count) / 3)   // several heard words must sound like it
        guard near || sounds(old, new), !(new == new.lowercased() && known(new)) else { return nil }
        return (old, new)
    }
    // The user's keys replayed over inserted words where the field can't be read back (terminals, some Electron apps).
    // key returns false once a key's effect on the text is unknown (Return, a shortcut, leaving the dictated words).
    struct Replay {
        var chars: [Character], at: Int
        init(_ text: String) { chars = Array(text); at = chars.count }
        var text: String { String(chars) }
        func wordStart() -> Int { var i = at; while i > 0, chars[i - 1].isWhitespace { i -= 1 }; while i > 0, !chars[i - 1].isWhitespace { i -= 1 }; return i }
        func wordEnd() -> Int { var i = at; while i < chars.count, chars[i].isWhitespace { i += 1 }; while i < chars.count, !chars[i].isWhitespace { i += 1 }; return i }
        mutating func key(_ code: Int, _ typed: String, option: Bool, control: Bool, command: Bool) -> Bool {
            if command { return false }
            switch (code, option, control) {
            case (51, false, false), (4, false, true):   // delete, ⌃H
                guard at > 0 else { return false }; at -= 1; chars.remove(at: at)
            case (51, true, false), (13, false, true):   // ⌥delete, ⌃W
                let start = wordStart(); guard start < at else { return false }; chars.removeSubrange(start..<at); at = start
            case (117, false, false): guard at < chars.count else { return false }; chars.remove(at: at)
            case (123, false, false): guard at > 0 else { return false }; at -= 1
            case (124, false, false): guard at < chars.count else { return false }; at += 1
            case (123, true, false): at = wordStart()
            case (124, true, false): at = wordEnd()
            default:   // arrows up/down, function keys, Return, Tab and Escape type control or private-use characters
                guard !control, !typed.isEmpty, !typed.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) || (0xF700...0xF8FF).contains($0.value) }) else { return false }
                chars.insert(contentsOf: typed, at: at); at += typed.count
            }
            return true
        }
    }
}
