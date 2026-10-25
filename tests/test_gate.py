"""Safe mode's gate: anything that deletes, changes a file, runs its own code or changes the system asks first; Rabik's
helpers, opening things and plain reads never do. Main asks also run in Claude Code's sandbox: a plain command stays in it,
and only a card the user allowed takes one out."""
import io
import json
import os
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.interaction, brain.macos, brain.paths, brain.policy, brain.prefs
from tests import scratch_dir

ME = shlex.quote(brain.paths.ME)
ASKS = {
    'python deletes a folder': "python3 -c \"import shutil; shutil.rmtree('/Users/x/Documents')\"",
    'python writes a file': "python3 -c \"open('/Users/x/.zshrc','w').write('')\"",
    'python reads code from stdin': "python3 - <<'EOF'\nimport os\nEOF",
    'perl deletes': "perl -e 'unlink q(/Users/x/a)'",
    'sh -c': "sh -c 'echo hi'",
    'bash runs decoded text': 'bash -c "$(echo cm0gLXJmIH4K | base64 -d)"',
    'substitution inside quotes': 'echo "$(python3 -c \'print(1)\')"',
    'backquotes': 'echo `node -e "1"`',
    'env wrapper': 'env -u X FOO=1 python3 x.py',
    'xargs': 'printf x | xargs -I {} python3 -c {}',
    'find -exec': 'find . -name "*.py" -exec python3 {} \\;',
    'eval': 'eval "$X"',
    'truncate': 'truncate -s 0 ~/Documents/thesis.docx',
    'cp over a file': 'cp /dev/null ~/Documents/thesis.docx',
    'sed in place': "sed -i '' 's/a/b/' ~/notes.txt",
    'wget': 'wget https://example.com/a',
    'pbpaste into a file': 'pbpaste > ~/Documents/thesis.docx',
    'a helper into a file': brain.paths.SEARCH + " 'x' > ~/Documents/thesis.docx",
    'mdfind into a file': 'mdfind -name foo > ~/.zshrc',
    'stderr into a file': 'ls 2> ~/.zshrc',
    'out of /tmp with ..': 'echo x > /tmp/../Users/x/.zshrc',
    'git clean': 'git clean -fdx',
    'pkill': 'pkill Safari',
}
RUNS = {
    'helper through python3': f'python3 {ME} --place Notes left current',
    'helper through sh': f'/bin/sh {ME} --hands see Notes',
    'helper through an alias': f'H={ME}; python3 "$H" --place Notes left current',
    'search text is not a command': brain.paths.SEARCH + " 'how to install python' 2>&1 | head -40",
    'open a search page': 'open "https://google.com/search?q=buy python shoes"',
    'AppleScript play/pause': "osascript -e 'tell application \"Music\" to playpause'",
    'find files': 'mdfind -name tokyo | head -20',
    'discarded and scratch output': 'osascript -e x 2>&1; ls >/dev/null; echo > /tmp/a',
    'read a page': "curl -s 'wttr.in/x?format=%l'",
    'read the clipboard': 'pbpaste',
    'menu path with >': brain.paths.HANDS + " menu Notes 'File > Export'",
    'date': 'date +%H:%M',
}


class GateTests(unittest.TestCase):
    def test_every_way_to_change_files_or_run_code_asks(self):
        for name, cmd in ASKS.items():
            with self.subTest(name):
                self.assertTrue(brain.policy.risky(cmd), cmd)

    def test_helpers_opens_and_reads_run_without_a_card(self):
        for name, cmd in RUNS.items():
            with self.subTest(name):
                self.assertEqual(brain.policy.risky(cmd), '', cmd)

    def test_main_ask_runs_a_risky_command_only_after_allow(self):
        root = scratch_dir(self)
        for answer, decision in (('n', 'deny'), ('y', 'allow')):
            event = {'tool_name': 'Bash', 'tool_input': {'command': 'pbpaste > ~/Documents/thesis.docx'}}
            with self.subTest(answer=answer), patch.dict(os.environ, {'RABIK_ASK': str(root)}), \
                 patch.object(brain.interaction, 'wait_commit', return_value=True), patch.object(brain.macos, 'preview_app'), \
                 patch.object(brain.interaction, 'ask_user', return_value=answer) as ask, \
                 patch('sys.stdin', io.StringIO(json.dumps(event))), patch('sys.stdout', new_callable=io.StringIO) as out:
                brain.policy.gate()
                self.assertEqual(ask.call_args.args[0]['q'], 'Change a file?')
                self.assertEqual(json.loads(out.getvalue())['hookSpecificOutput']['permissionDecision'], decision)


    def test_main_ask_leaves_the_sandbox_only_through_a_card(self):
        # No decision = Claude Code runs it in the sandbox. Asking to leave it, or a risky command, waits for the card;
        # what the user allowed runs for real. Full access has no sandbox and no card for leaving it.
        root = scratch_dir(self)
        def gate(inp, answer='n', safe=True):
            event = {'tool_name': 'Bash', 'tool_input': inp}
            with patch.dict(os.environ, {'RABIK_ASK': str(root)}), patch.object(brain.interaction, 'wait_commit', return_value=True), \
                 patch.object(brain.prefs, 'pref', side_effect=lambda k, d: safe if k == 'safe' else d), patch.object(brain.macos, 'preview_app'), \
                 patch.object(brain.interaction, 'ask_user', return_value=answer) as ask, \
                 patch('sys.stdin', io.StringIO(json.dumps(event))), patch('sys.stdout', new_callable=io.StringIO) as out:
                brain.policy.gate()
            return (json.loads(out.getvalue())['hookSpecificOutput'] if out.getvalue() else {}), ask
        decision, ask = gate({'command': 'mkdir ~/Desktop/Reports'})
        self.assertEqual(decision, {}); ask.assert_not_called()
        for answer, verdict in (('n', 'deny'), ('y', 'allow')):
            with self.subTest(answer=answer):
                decision, ask = gate({'command': 'mkdir ~/Desktop/Reports', 'dangerouslyDisableSandbox': True}, answer)
                self.assertEqual(ask.call_args.args[0]['q'], 'Run outside the safe folder?')
                self.assertEqual(decision['permissionDecision'], verdict)
        self.assertTrue(decision['updatedInput']['dangerouslyDisableSandbox'])
        decision, ask = gate({'command': 'pbpaste > ~/Documents/thesis.docx'}, 'y')
        self.assertEqual(ask.call_args.args[0]['q'], 'Change a file?')
        self.assertTrue(decision['updatedInput']['dangerouslyDisableSandbox'])
        decision, ask = gate({'command': 'mkdir ~/Desktop/Reports', 'dangerouslyDisableSandbox': True}, safe=False)
        self.assertEqual(decision, {}); ask.assert_not_called()

if __name__ == '__main__':
    unittest.main()
