"""Fifteen task eval scenarios (apps with no Atticus special-casing). Stdlib only."""
from copy import deepcopy

WORKSHEET_P1 = """Algebra practice (page 1 of 2)
1. 2x + 4 = 10  answer: ___
2. 3y - 1 = 8   answer: ___
3. x² = 16       answer: ___
4. 5a = 20       answer: ___
5. b/2 = 3       answer: ___
(more on next page)"""

WORKSHEET_P2 = """Algebra practice (page 2 of 2)
6. 4m + 2 = 14  answer: ___
7. 9 - n = 4    answer: ___
8. 2p = 18      answer: ___
9. q + 7 = 15   answer: ___
10. 3r - 6 = 0  answer: ___"""

WORKSHEET_PAD = 'Study tip: show each step before you box the answer.\n' * 420
WORKSHEET_DOC = WORKSHEET_P1 + '\n' + WORKSHEET_PAD + WORKSHEET_P2

# Universal reader OCR kicks in below ~160 chars; keep fixture documents longer.
def _doc(text):
    return text if len(text) >= 200 else text + '\n' + ('(context padding)\n' * 12)

SCENARIOS = [
    {
        'id': 'worksheet_browser',
        'task': 'Fill in answers 1 through 10 on this algebra worksheet in the browser.',
        'front_app': 'Orbit Browser',
        'front_window': 'Algebra worksheet',
        'browser': 'Orbit Browser',
        'url': 'https://class.example/algebra',
        'pages': {
            'default': {
                'title': 'Algebra worksheet',
                'body': WORKSHEET_P1,
                'controls': [
                    {'kind': 'box', 'label': 'Q1 answer'},
                    {'kind': 'box', 'label': 'Q2 answer'},
                    {'kind': 'box', 'label': 'Q3 answer'},
                    {'kind': 'box', 'label': 'Q4 answer'},
                    {'kind': 'box', 'label': 'Q5 answer'},
                    {'kind': 'link', 'label': 'Next page', 'goto_page': 'p2', 'effect': 'read_page2'},
                ],
            },
            'p2': {
                'title': 'Algebra worksheet p2',
                'body': WORKSHEET_P2,
                'controls': [
                    {'kind': 'box', 'label': 'Q6 answer'},
                    {'kind': 'box', 'label': 'Q7 answer'},
                    {'kind': 'box', 'label': 'Q8 answer'},
                    {'kind': 'box', 'label': 'Q9 answer'},
                    {'kind': 'box', 'label': 'Q10 answer', 'effect': 'filled_q10'},
                ],
            },
        },
        'document': WORKSHEET_DOC,
        'expect': {'effects': ['read_page2', 'filled_q10'], 'control_values': {'p2': {'Q10 answer': '2'}},
                   'text_before_look': True},
        'dry_bash': [
            f'python3 "$ATTICUS_ME" --web read',
            f'python3 "$ATTICUS_ME" --web fill 1 "3"',
            f'python3 "$ATTICUS_ME" --web click 6',
            f'python3 "$ATTICUS_ME" --web read',
            f'python3 "$ATTICUS_ME" --web fill 5 "2"',
        ],
    },
    {
        'id': 'survey_form',
        'task': 'Submit this volunteer signup form with name Alex Lee and grade 10.',
        'front_app': 'Nebula Browser',
        'front_window': 'Volunteer signup',
        'browser': 'Nebula Browser',
        'url': 'https://forms.example/volunteer',
        'document': _doc('Volunteer signup\nName:\nGrade:\nEmail optional\nFull name box, Grade box, Submit button.'),
        'pages': {'default': {
            'title': 'Volunteer signup',
            'body': 'Name:\nGrade:\nEmail optional',
            'controls': [
                {'kind': 'box', 'label': 'Full name'},
                {'kind': 'box', 'label': 'Grade'},
                {'kind': 'button', 'label': 'Submit', 'what': 'submits form', 'effect': 'form_submitted'},
            ],
        }},
        'expect': {'effects': ['form_submitted'], 'text_before_look': True},
        'dry_bash': [
            'python3 "$ATTICUS_ME" --web read',
            'python3 "$ATTICUS_ME" --web fill 1 "Alex Lee"',
            'python3 "$ATTICUS_ME" --web fill 2 "10"',
            'python3 "$ATTICUS_ME" --web click 3',
        ],
    },
    {
        'id': 'pdf_preview',
        'task': 'Summarize this PDF for me.',
        'front_app': 'Preview',
        'front_window': 'Biology_ch3.pdf',
        'hands': {
            'description': '1 text: Mitochondria are the powerhouse of the cell. Chloroplasts capture light.',
            'nodes': [{'id': 1, 'role': 'AXStaticText', 'label': 'Mitochondria are the powerhouse of the cell.'}],
        },
        'document': _doc('Mitochondria are the powerhouse of the cell. Chloroplasts capture light.'),
        'expect': {'answer_contains': ['mitochondria', 'chloroplast'], 'text_before_look': True},
        'dry_bash': [],
        'dry_result': 'Mitochondria are the powerhouse of the cell; chloroplasts capture light.',
    },
    {
        'id': 'pages_summarize',
        'task': 'Summarize this document.',
        'front_app': 'Pages',
        'front_window': 'Trip notes',
        'hands': {
            'description': '1 text: Day 1: flew to Lisbon. Day 2: walked Alfama.',
            'nodes': [{'id': 1, 'role': 'AXStaticText', 'label': 'Day 1: flew to Lisbon.'}],
        },
        'document': _doc('Day 1: flew to Lisbon. Day 2: walked Alfama.'),
        'expect': {'answer_contains': ['Lisbon', 'Alfama'], 'text_before_look': True},
        'dry_bash': [],
        'dry_result': 'Day 1 flew to Lisbon; day 2 walked Alfama.',
    },
    {
        'id': 'spreadsheet_total',
        'task': 'What is the total of column B in this sheet?',
        'front_app': 'CalcSheet',
        'front_window': 'Budget Q1',
        'hands': {
            'description': 'Column B rows: 120, 45, 30, 5',
            'nodes': [{'id': 1, 'role': 'AXTable', 'label': 'Sheet'}],
        },
        'document': _doc('Column B rows: 120, 45, 30, 5'),
        'expect': {'answer_contains': ['200'], 'text_before_look': True},
        'dry_bash': [],
        'dry_result': 'The total of column B is 200.',
    },
    {
        'id': 'settings_toggle',
        'task': 'Turn on notifications in this app settings.',
        'front_app': 'PixelForge',
        'front_window': 'Settings',
        'hands': {
            'description': '1 checkbox: Enable notifications (off)',
            'nodes': [{'id': 1, 'role': 'AXCheckBox', 'label': 'Enable notifications', 'effect': 'notifications_on'}],
        },
        'expect': {'effects': ['notifications_on'], 'text_before_look': True},
        'dry_bash': ['python3 "$ATTICUS_ME" --hands click 1'],
    },
    {
        'id': 'native_button',
        'task': 'Click Export in this window.',
        'front_app': 'DraftPad',
        'front_window': 'Essay',
        'hands': {
            'description': '1 button: Export',
            'nodes': [{'id': 1, 'role': 'AXButton', 'label': 'Export', 'effect': 'exported'}],
        },
        'expect': {'effects': ['exported'], 'text_before_look': True},
        'dry_bash': ['python3 "$ATTICUS_ME" --hands click 1'],
    },
    {
        'id': 'shop_cheapest_cart',
        'task': 'Add the cheapest item on this page to the cart. Do not buy or checkout.',
        'front_app': 'Wave Browser',
        'front_window': 'Gadget shop',
        'browser': 'Wave Browser',
        'url': 'https://shop.example/gadgets',
        'document': _doc('Gadget shop\nCable $12\nAdapter $8\nCase $15\nAdd Cable to cart, Add Adapter to cart, Buy now.'),
        'pages': {'default': {
            'title': 'Gadget shop',
            'body': 'Cable $12\nAdapter $8\nCase $15',
            'controls': [
                {'kind': 'button', 'label': 'Add Cable to cart', 'effect': 'cart_cable'},
                {'kind': 'button', 'label': 'Add Adapter to cart', 'effect': 'cart_adapter'},
                {'kind': 'button', 'label': 'Buy now', 'what': 'buy checkout', 'effect': 'purchased'},
            ],
        }},
        'expect': {'effects': ['cart_adapter'], 'forbid_effects': ['purchased'], 'text_before_look': True},
        'dry_bash': [
            'python3 "$ATTICUS_ME" --web read',
            'python3 "$ATTICUS_ME" --web click 2',
        ],
    },
    {
        'id': 'mail_reply',
        'task': 'Reply to this email saying I will be there at 4.',
        'front_app': 'Postbox',
        'front_window': 'Re: Meeting',
        'hands': {
            'description': '1 button: Reply\n2 box: Message',
            'nodes': [
                {'id': 1, 'role': 'AXButton', 'label': 'Reply', 'effect': 'reply_open'},
                {'id': 2, 'role': 'AXTextArea', 'label': 'Message', 'effect': 'reply_typed'},
            ],
        },
        'expect': {'effects': ['reply_open'], 'forbid_effects': ['sent_mail'], 'text_before_look': True},
        'dry_bash': [
            'python3 "$ATTICUS_ME" --hands click 1',
            'python3 "$ATTICUS_ME" --hands type 2 "I will be there at 4."',
        ],
    },
    {
        'id': 'menu_bar_wifi',
        'task': 'Turn Wi-Fi off from the menu bar.',
        'front_app': 'Finder',
        'front_window': 'Desktop',
        'hands': {
            'description': 'menu bar: Wi-Fi on',
            'nodes': [{'id': 1, 'role': 'AXMenuBarItem', 'label': 'Wi-Fi', 'effect': 'wifi_menu'}],
        },
        'expect': {'tool_patterns': [r'--hands'], 'text_before_look': True},
        'dry_bash': ['python3 "$ATTICUS_ME" --hands menu Finder Wi-Fi'],
    },
    {
        'id': 'calendar_event',
        'task': 'Create a calendar event tomorrow at 3pm called Dentist.',
        'front_app': 'Chrono',
        'front_window': 'Calendar',
        'hands': {
            'description': '1 button: New Event',
            'nodes': [{'id': 1, 'role': 'AXButton', 'label': 'New Event', 'effect': 'event_started'}],
        },
        'expect': {'effects': ['event_started'], 'text_before_look': True},
        'dry_bash': ['python3 "$ATTICUS_ME" --hands click 1'],
    },
    {
        'id': 'on_screen_question',
        'task': 'Answer the question on my screen.',
        'front_app': 'StudyPane',
        'front_window': 'Quiz',
        'hands': {
            'description': 'Question: What is 7 × 8?  Answer box below.',
            'nodes': [{'id': 1, 'role': 'AXStaticText', 'label': 'What is 7 × 8?'}],
        },
        'document': _doc('Question: What is 7 × 8?  Answer box below.'),
        'expect': {'answer_contains': ['56'], 'forbid_tool_patterns': [r'--look'], 'text_before_look': True},
        'dry_bash': [],
        'dry_result': '7 × 8 is 56.',
    },
    {
        'id': 'chart_colors',
        'task': 'Which color has the tallest bar in this chart?',
        'front_app': 'ChartLab',
        'front_window': 'Sales chart',
        'hands': {'description': 'chart image (no readable values)', 'nodes': []},
        'ocr': 'Sales chart — red 40, green 55, blue 80 (tallest bar is blue).',
        'expect': {'answer_contains': ['blue'], 'text_before_look': False},
        'dry_bash': ['python3 "$ATTICUS_ME" --look'],
        'dry_result': 'Blue has the tallest bar.',
    },
    {
        'id': 'finder_multistep',
        'task': 'Move the file report.pdf from Downloads to the Archive folder in Documents.',
        'front_app': 'Finder',
        'front_window': 'Downloads',
        'hands': {
            'description': '1 row: report.pdf\n2 folder: Archive',
            'nodes': [
                {'id': 1, 'role': 'AXRow', 'label': 'report.pdf', 'effect': 'selected_report'},
                {'id': 2, 'role': 'AXButton', 'label': 'Move to Archive', 'effect': 'moved_report'},
            ],
        },
        'expect': {'effects': ['moved_report'], 'text_before_look': True},
        'dry_bash': [
            'python3 "$ATTICUS_ME" --hands click 1',
            'python3 "$ATTICUS_ME" --hands click 2',
        ],
    },
    {
        'id': 'ambiguous_which',
        'task': 'Open the document.',
        'front_app': 'Finder',
        'front_window': 'Documents',
        'hands': {
            'description': '1 row: Budget.pdf\n2 row: Budget draft.pdf',
            'nodes': [
                {'id': 1, 'role': 'AXRow', 'label': 'Budget.pdf'},
                {'id': 2, 'role': 'AXRow', 'label': 'Budget draft.pdf'},
            ],
        },
        'expect': {'tool_patterns': [r'--pick']},
        'live_expect': {'max_clarify_questions': 1},
        'dry_bash': ['python3 "$ATTICUS_ME" --pick "Which document?" "Budget.pdf" "Budget draft.pdf"'],
    },
]


def initial_state(scenario):
    s = deepcopy(scenario)
    for key in ('expect', 'dry_bash', 'dry_result', 'live_expect', 'task', 'id'):
        s.pop(key, None)
    s.setdefault('page', 'default')
    s.setdefault('effects', [])
    s.setdefault('pid', 4242)
    return s


def by_id(scenario_id):
    for s in SCENARIOS:
        if s['id'] == scenario_id:
            return s
    raise KeyError(scenario_id)
