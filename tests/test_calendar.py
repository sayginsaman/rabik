"""Calendar tools use fake events, cards and native stores, never personal calendars."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests import scratch_dir, run_swift
import atticus


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        self.env = patch.dict(os.environ, {'ATTICUS_ASK': str(self.root)}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.event = dict(id='one', title='Dentist', start='2026-10-19T15:00:00-07:00',
                          end='2026-10-19T16:30:00-07:00', calendar='Personal', calendarID='cal', writable=True, allDay=False)
        self.calls = []
        self.events = [self.event]
        def backend(data):
            self.calls.append(data)
            return {'events': self.events} if data['action'] == 'list' else {'saved': True}
        self.backend = patch.object(atticus, 'calendar_backend', side_effect=backend)
        self.backend.start(); self.addCleanup(self.backend.stop)
        self.data = dict(action='move', query='Dentist', **{'from': '2026-10-19T00:00:00-07:00', 'to': '2026-10-20T00:00:00-07:00'},
                         start='2026-10-19T16:00:00-07:00')

    def tool(self, **changes):
        return atticus.calendar_tool([json.dumps({**self.data, **changes}, ensure_ascii=False)])

    def test_move_keeps_duration_and_shows_old_new(self):
        with patch.object(atticus, 'ask_user', return_value='y') as card:
            self.assertIn('saved', self.tool())
        self.assertEqual(self.calls[-1]['end'], '2026-10-19T17:30:00-07:00')
        self.assertEqual(self.calls[-1]['event'], self.event)
        self.assertIn('Dentist', card.call_args.args[0]['cmd'])
        self.assertIn('3:00 PM', card.call_args.args[0]['cmd'])
        self.assertIn('→ Mon Oct 19, 4:00 PM', card.call_args.args[0]['cmd'])
        self.assertTrue(card.call_args.args[0]['cmd'].startswith('Dentist → Mon Oct 19, 4:00 PM'))   # the change leads, so the one-line card shows it
        self.assertIn('– 5:30 PM', card.call_args.args[0]['cmd'])   # same day: the date is not repeated

    def test_explicit_end(self):
        with patch.object(atticus, 'ask_user', return_value='y'):
            self.tool(end='2026-10-19T18:00:00-07:00')
        self.assertEqual(self.calls[-1]['end'], '2026-10-19T18:00:00-07:00')

    def test_ambiguous_pick_before_confirmation(self):
        self.events.append({**self.event, 'id': 'two', 'calendar': 'Work'})
        with patch.object(atticus, 'ask_user', side_effect=['1', 'y']) as card:
            self.tool()
        self.assertIn('pick', card.call_args_list[0].args[0])
        self.assertEqual(len(card.call_args_list[0].args[0]['options']), 2)
        self.assertIn('q', card.call_args_list[1].args[0])
        self.assertLessEqual(card.call_args_list[1].args[1], card.call_args_list[0].args[1])
        self.assertEqual(self.calls[-1]['event']['id'], 'two')

    def test_ambiguous_without_pick_never_writes(self):
        self.events.append({**self.event, 'id': 'two'})
        with patch.object(atticus, 'ask_user', return_value=None):
            self.assertIn('No event selected', self.tool(query=''))
        self.assertEqual(len(self.calls), 1)

    def test_delete_asks_before_write_even_safe_mode_off(self):
        with patch.object(atticus, 'ask_user', return_value='n') as card:
            self.assertIn('No change', self.tool(action='delete'))
        self.assertEqual(len(self.calls), 1)
        self.assertIn('Dentist', card.call_args.args[0]['cmd'])
        self.assertIn('→ Deleted', card.call_args.args[0]['cmd'])
        with patch.object(atticus, 'ask_user', return_value='y'):
            self.tool(action='delete')
        self.assertEqual(self.calls[-1]['action'], 'delete')

    def test_person_match_uses_attendees_not_just_title(self):
        self.event.update(title='Review', attendees=['Alex mailto:alex@example.test'])
        with patch.object(atticus, 'ask_user', return_value='y') as card:
            self.assertIn('saved', self.tool(action='delete', query='Alex'))
        self.assertIn('Alex', card.call_args.args[0]['cmd'])
        self.assertEqual(self.calls[-1]['event']['title'], 'Review')

    def test_no_card_channel_never_changes_existing_event(self):
        os.environ.pop('ATTICUS_ASK')
        self.assertIn('approval is required', self.tool(action='delete'))
        self.assertEqual(len(self.calls), 1)

    def test_permission_uses_allow_chip(self):
        with patch.object(atticus, 'calendar_backend', return_value={'need': 'calendar'}), \
             patch.object(atticus, 'ask_user', return_value='y') as card:
            self.assertIn('Calendar is on', self.tool())
        self.assertEqual(card.call_args.args[0]['need'], 'calendar')

    def test_add_needs_no_extra_confirmation(self):
        with patch.object(atticus, 'ask_user') as card:
            self.tool(action='add', title='Study', end='2026-10-19T17:00:00-07:00')
        card.assert_not_called()
        self.assertEqual(self.calls[0]['action'], 'add')

    def test_multilingual_request_has_same_tool_and_cli(self):
        # Fake the model choosing the documented tool; language interpretation stays with the model.
        for request, title in [('Mueve mi cita al viernes', 'Dentista'), ('把学习时间改到四点', '学习')]:
            os.environ['ATTICUS_REQUEST'] = request
            self.events = [{**self.event, 'title': title}]
            with patch.object(atticus, 'ask_user', return_value='y'), \
                 patch.object(sys, 'argv', ['atticus.py', '--calendar', json.dumps({**self.data, 'query': title}, ensure_ascii=False)]), \
                 patch('sys.stdout', new_callable=io.StringIO) as out:
                atticus.main()
            self.assertIn('saved', out.getvalue())
            self.assertEqual(self.calls[-1]['event']['title'], title)
        self.assertIn('Calendar (any language)', atticus.SYSTEM)
        self.assertIn('--calendar', atticus.system_prompt(atticus.ASK_FIRST))

    def test_validation_and_read_only_prep(self):
        for changes in [dict(query=3), dict(start='tomorrow'), dict(end='2026-10-19T14:00:00-07:00'), dict(start='2026-10-19T16:00:00')]:
            self.assertIn('could not finish', self.tool(**changes))
        self.assertEqual(self.calls, [])
        os.environ['ATTICUS_AGENT_PREP'] = '1'
        self.assertIn('read-only', self.tool())
        self.assertEqual(self.calls, [])

    def test_confirmation_cancel_and_readonly(self):
        with patch.object(atticus, 'wait_commit', return_value=False):
            self.assertIn('cancelled', self.tool())
        self.assertEqual(self.calls, [])
        self.event['writable'] = False
        with patch.object(atticus, 'ask_user') as card:
            self.assertIn('read-only', self.tool())
        card.assert_not_called()

    def test_help_and_backend_transport(self):
        self.assertIn('preserves duration', atticus.calendar_tool(['--help']))
        self.backend.stop()
        with patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"events":[]}')) as run:
            self.assertEqual(atticus.calendar_backend({'action': 'list'}), {'events': []})
        self.assertEqual(run.call_args.args[0], [atticus.APP, '--calendar'])
        self.assertEqual(json.loads(run.call_args.kwargs['input']), {'action': 'list'})
        self.assertFalse(atticus.risky(atticus.ME + ' --calendar \'{"action":"delete"}\''))

    def test_model_cannot_call_native_calendar_directly(self):
        event = {'tool_name': 'Bash', 'tool_input': {}}
        for tail in ('', ';', '&', "<<<'{}'"):
            with self.subTest(tail=tail):
                event['tool_input']['command'] = atticus.APP + ' --calendar' + tail
                with patch('sys.stdin', io.StringIO(json.dumps(event))), patch('sys.stdout', new_callable=io.StringIO) as out:
                    atticus.gate()
                self.assertTrue(out.getvalue(), 'Native calendar request bypassed the gate')
                result = json.loads(out.getvalue())['hookSpecificOutput']
                self.assertEqual(result['permissionDecision'], 'deny')
                self.assertIn('--calendar', result['permissionDecisionReason'])
        event['tool_input']['command'] = atticus.ME + ' --calendar \'{"action":"add","title":"Atticus"}\''
        with patch('sys.stdin', io.StringIO(json.dumps(event))), patch('sys.stdout', new_callable=io.StringIO) as out, \
             patch.object(atticus, 'preview_commands'):
            atticus.gate()
        self.assertEqual(out.getvalue(), '')


@unittest.skipUnless(sys.platform == 'darwin', 'Swift calendar backend')
class CalendarNativeTests(unittest.TestCase):
    def test_eventkit_logic_with_fake_store(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        tool = source[source.index('enum CalendarTool {'):source.index('\nfunc currentMeetingEvent(')]
        fake = r'''
import Foundation
struct Kind: Equatable { static let event = Kind(); static let fullAccess = Kind(); static let denied = Kind() }
// A distinct permission value without touching macOS privacy or real EventKit.
enum Authorization { case fullAccess, denied }
enum Span { case thisEvent }
enum Status { case none, canceled }
class EKCalendar {
    var calendarIdentifier = "cal"; var title = "Fixture"; var allowsContentModifications = true
}
struct Participant { var name: String?; var url: URL }
class EKEvent {
    var attendees: [Participant]? = [Participant(name:"Alex",url:URL(string:"mailto:alex@example.test")!)]
    var eventIdentifier: String? = "one"; var title: String? = "Fixture event"
    var startDate: Date!; var endDate: Date!; var calendar: EKCalendar! = EKCalendar()
    var isAllDay = false; var lastModifiedDate: Date? = Date(timeIntervalSince1970: 100)
    var status = Status.none
    init(eventStore: EKEventStore) {}
}
class EKEventStore {
    static var permission = Authorization.fullAccess
    static func authorizationStatus(for kind: Kind) -> Authorization { permission }
    var rows = [EKEvent](); var saved = 0; var removed = 0; var lastSpan: Span?
    var defaultCalendarForNewEvents: EKCalendar? = EKCalendar()
    func calendars(for kind: Kind) -> [EKCalendar] { [defaultCalendarForNewEvents! ] }
    func calendar(withIdentifier id: String) -> EKCalendar? { id == "cal" ? defaultCalendarForNewEvents : nil }
    func predicateForEvents(withStart start: Date, end: Date, calendars: [EKCalendar]?) -> (Date, Date) { (start,end) }
    func events(matching range: (Date, Date)) -> [EKEvent] { rows.filter { $0.startDate < range.1 && $0.endDate > range.0 } }
    func save(_ event: EKEvent, span: Span, commit: Bool) throws { saved += 1; lastSpan = span; rows = [event] }
    func remove(_ event: EKEvent, span: Span, commit: Bool) throws { removed += 1; lastSpan = span; rows = [] }
}
'''
        checks = r'''
let store = EKEventStore()
let original = EKEvent(eventStore: store)
original.startDate = CalendarTool.date("2026-10-19T15:00:00-07:00")!
original.endDate = original.startDate.addingTimeInterval(5400)
store.rows = [original]
let range: [String: Any] = ["action":"list","from":"2026-10-19T00:00:00-07:00","to":"2026-10-20T00:00:00-07:00"]
let listed = try! CalendarTool.run(range, store:store)
let event = (listed["events"] as! [[String:Any]])[0]
precondition(event["calendarID"] as? String == "cal")
var personRange = range; personRange["query"] = "Alex"
precondition((try! CalendarTool.run(personRange,store:store)["events"] as! [[String:Any]]).count == 1)
personRange["query"] = "Absent"
precondition((try! CalendarTool.run(personRange,store:store)["events"] as! [[String:Any]]).isEmpty)
precondition((listed["calendars"] as! [[String:Any]]).count == 1)
var move: [String: Any] = ["action":"move","event":event,"start":"2026-10-19T23:00:00.000Z","end":"2026-10-20T00:30:00Z"]
original.title = "Changed while waiting"
precondition(try! CalendarTool.run(move, store:store)["error"] != nil)
precondition(store.saved == 0)
original.title = "Fixture event"
let moved = try! CalendarTool.run(move, store:store)
precondition(moved["event"] != nil && store.saved == 1 && store.lastSpan == .thisEvent)
precondition(original.endDate.timeIntervalSince(original.startDate) == 5400)
// An identical ID at another occurrence time must not redirect the change.
let occurrence = CalendarTool.row(original)
let other = EKEvent(eventStore:store); other.startDate = original.startDate.addingTimeInterval(86400); other.endDate = other.startDate.addingTimeInterval(5400)
store.rows.append(other)
let deleted = try! CalendarTool.run(["action":"delete","event":occurrence], store:store)
precondition(deleted["deleted"] != nil && store.removed == 1 && store.lastSpan == .thisEvent)
var add: [String:Any] = ["action":"add","title":"学习","start":"2026-10-19T23:00:00Z","end":"2026-10-20T00:00:00Z"]
precondition(try! CalendarTool.run(add, store:store)["event"] != nil)
add["calendarID"] = "missing"
precondition(try! CalendarTool.run(add, store:store)["error"] != nil)
add.removeValue(forKey:"calendarID"); store.defaultCalendarForNewEvents!.allowsContentModifications = false
precondition(try! CalendarTool.run(add, store:store)["error"] != nil)
EKEventStore.permission = .denied
precondition(try! CalendarTool.run(range, store:store)["need"] as? String == "calendar")
precondition(try! CalendarTool.run(add, store:store)["need"] as? String == "calendar")
print("fake EventKit calendar ok")
'''
        self.assertIn('fake EventKit calendar ok', run_swift(self, fake + tool + checks))
