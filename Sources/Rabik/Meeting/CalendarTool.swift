// Calendar for the brain (--calendar). Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
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

// Structured EventKit backend; the Python tool owns picks and approval cards.
enum CalendarTool {
    static func date(_ value: Any?) -> Date? {
        guard let text = value as? String else { return nil }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = f.date(from: text) { return date }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: text)
    }
    static func row(_ event: EKEvent) -> [String: Any] {
        let f = ISO8601DateFormatter(); f.timeZone = .current; f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let attendees = (event.attendees ?? []).map { [$0.name ?? "", $0.url.absoluteString.replacingOccurrences(of: "mailto:", with: "")].joined(separator: " ") }
        return ["id": event.eventIdentifier ?? "", "title": event.title ?? "", "start": f.string(from: event.startDate),
                "end": f.string(from: event.endDate), "calendarID": event.calendar.calendarIdentifier,
                "calendar": event.calendar.title, "writable": event.calendar.allowsContentModifications, "allDay": event.isAllDay,
                "attendees": attendees,
                "modified": event.lastModifiedDate.map { f.string(from: $0) } ?? ""]
    }
    static func day(_ value: Any?) -> DateComponents? {   // "2026-10-27": a due day, no time
        let parts = (value as? String ?? "").split(separator: "-", omittingEmptySubsequences: false).map { Int($0) }
        guard parts.count == 3, let year = parts[0], let month = parts[1], let day = parts[2] else { return nil }
        let calendar = Calendar(identifier: .gregorian)
        guard let date = calendar.date(from: DateComponents(year: year, month: month, day: day)),
              calendar.component(.month, from: date) == month, calendar.component(.day, from: date) == day else { return nil }
        return DateComponents(year: year, month: month, day: day)
    }
    // Reminders: the lists to add to, and adding the action items the user picked. The brain decides which items and keeps their
    // "added" marks; an add is all or nothing, so a mark never names a reminder that was not saved.
    static func reminders(_ data: [String: Any], store: EKEventStore) throws -> [String: Any] {
        guard EKEventStore.authorizationStatus(for: .reminder) == .fullAccess else { return ["need": "reminders"] }
        let lists = store.calendars(for: .reminder).filter { $0.allowsContentModifications }
        let fallback = store.defaultCalendarForNewReminders()
        if data["action"] as? String == "reminderLists" {
            return ["lists": lists.map { ["id": $0.calendarIdentifier, "title": $0.title, "isDefault": $0.calendarIdentifier == fallback?.calendarIdentifier] as [String: Any] }]
        }
        guard let items = data["items"] as? [[String: Any]], (1...20).contains(items.count),
              items.allSatisfy({ !(($0["title"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else { return ["error": "Give 1 to 20 items with titles."] }
        let wanted = data["list"] as? String ?? "", chosen = lists.first { $0.calendarIdentifier == wanted }
        guard let target = chosen ?? fallback ?? lists.first else { return ["error": "Reminders has no list to add to."] }
        var added: [String] = []
        do {
            for item in items {
                let reminder = EKReminder(eventStore: store)
                reminder.calendar = target; reminder.title = String((item["title"] as? String ?? "").prefix(300)); reminder.notes = item["notes"] as? String
                reminder.dueDateComponents = day(item["due"])
                try store.save(reminder, commit: false); added.append(reminder.calendarItemIdentifier)
            }
            try store.commit()
        } catch { store.reset(); throw error }
        return ["added": added, "list": target.title, "fellBack": !wanted.isEmpty && chosen == nil]
    }
    static func run(_ data: [String: Any], store: EKEventStore = EKEventStore()) throws -> [String: Any] {
        if ["reminderLists", "addReminders"].contains(data["action"] as? String ?? "") { return try reminders(data, store: store) }
        guard EKEventStore.authorizationStatus(for: .event) == .fullAccess else { return ["need": "calendar"] }
        let action = data["action"] as? String ?? ""
        if action == "list" {
            guard let start = date(data["from"]), let end = date(data["to"]), end > start,
                  end.timeIntervalSince(start) <= 4 * 365 * 86400 else { return ["error": "Use a valid range shorter than four years."] }
            let query = data["query"] as? String ?? ""
            let events = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: nil))
                .filter { $0.status != .canceled }.sorted { $0.startDate < $1.startDate }.map { row($0) }
            return ["events": events.filter { query.isEmpty || ([$0["title"] as? String ?? ""] + ($0["attendees"] as? [String] ?? [])).joined(separator: " ").localizedCaseInsensitiveContains(query) }, "calendars": store.calendars(for: .event).map {
                ["id": $0.calendarIdentifier, "title": $0.title, "writable": $0.allowsContentModifications] as [String: Any]
            }]
        }
        guard ["add", "move", "delete"].contains(action) else { return ["error": "Unknown calendar action."] }
        let event: EKEvent
        if action == "add" {
            guard let title = data["title"] as? String, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return ["error": "A title is required."] }
            let target = (data["calendarID"] as? String).flatMap { store.calendar(withIdentifier: $0) } ?? (data["calendarID"] == nil ? store.defaultCalendarForNewEvents : nil)
            guard let target, target.allowsContentModifications else { return ["error": "Choose a writable calendar from list."] }
            event = EKEvent(eventStore: store); event.calendar = target; event.title = title
        } else {
            guard let expected = data["event"] as? [String: Any], let start = date(expected["start"]), let end = date(expected["end"]) else { return ["error": "Read the event before changing it."] }
            // Query the occurrence: recurring events may share an identifier.
            let matches = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: nil))
                .filter { NSDictionary(dictionary: row($0)).isEqual(to: expected) }
            guard matches.count == 1 else { return ["error": "Event changed or disappeared. Read it again and ask for approval again."] }
            event = matches[0]
            guard event.calendar.allowsContentModifications else { return ["error": "This calendar is read-only."] }
        }
        if action == "delete" {
            try store.remove(event, span: .thisEvent, commit: true)
            return ["deleted": data["event"] ?? [:]]
        }
        guard let start = date(data["start"]), let end = date(data["end"]), end > start else { return ["error": "Use a start and a later end with timezone offsets."] }
        event.startDate = start; event.endDate = end
        try store.save(event, span: .thisEvent, commit: true)
        return ["event": row(event)]
    }
}
