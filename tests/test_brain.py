"""brain/'s layering rules, and rabik.py's compatibility facade for callers that still know rabik.py as the whole brain."""
import ast
import graphlib
import importlib
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import rabik
import brain.hands, brain.paths, brain.prefs, brain.skills, brain.storage, brain.turn

ROOT = Path(__file__).resolve().parents[1]
MODULES = sorted((ROOT / 'brain').glob('*.py'))


def imports(path):
    return [node for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, (ast.Import, ast.ImportFrom))]


class BrainTests(unittest.TestCase):
    def test_brain_never_imports_the_entry_script(self):
        for path in MODULES:
            with self.subTest(path.name):
                names = [a.name for n in imports(path) for a in n.names] + [n.module or '' for n in imports(path) if isinstance(n, ast.ImportFrom)]
                self.assertFalse([n for n in names if n.split('.')[0] == 'rabik'])

    def test_siblings_are_called_through_their_module(self):
        # `from brain.prefs import pref` would keep the unpatched function: a patch reaches brain only as prefs.pref.
        # prompts alone takes paths' helper commands by name, because its texts are built once, at import.
        for path in MODULES:
            for node in imports(path):
                if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('brain.'):
                    with self.subTest(f'{path.name}: from {node.module}'):
                        self.assertEqual((path.name, node.module), ('prompts.py', 'brain.paths'))

    def test_brain_has_no_import_cycle(self):
        # The layers depend one way (paths, then prefs and storage, ... ask, then cli): a cycle would not fail at import,
        # it would hand one module the other half-built.
        deps = {path.stem: {a.name for n in imports(path) if isinstance(n, ast.ImportFrom) and n.module == 'brain' for a in n.names}
                for path in MODULES}
        list(graphlib.TopologicalSorter(deps).static_order())   # CycleError names the loop

    def test_every_moved_name_is_the_same_object_on_the_facade(self):
        modules = {importlib.import_module('brain.' + path.stem) for path in MODULES if path.stem != '__init__'}
        self.assertEqual(set(rabik._OWNERS.values()), modules)   # a module left out of _OWNERS would miss every patch
        for module in modules:
            for name in module.__all__:
                with self.subTest(f'{module.__name__}.{name}'):
                    self.assertIs(getattr(rabik, name), getattr(module, name))

    def test_a_patch_on_the_facade_reaches_the_owner_and_is_undone(self):
        # What the eval harness does, against this checkout or an old single-file one.
        original = brain.prefs.pref
        with patch.object(rabik, 'pref', side_effect=lambda key, default: 'pi' if key == 'client' else default):
            self.assertIsNot(brain.prefs.pref, original)
            self.assertEqual(brain.prefs.client(), 'pi')   # brain.prefs.client reads the patched pref
        self.assertIs(brain.prefs.pref, original)
        self.assertIs(rabik.pref, original)

    def test_unit_tests_patch_the_owner_not_the_facade(self):
        # A unit test names the brain module that owns what it patches; the facade is for the eval harness, scripts tests
        # start in a subprocess (import rabik; rabik.show(...)) and the selftest. test_feedback checks the facade's surface.
        for path in sorted((ROOT / 'tests').glob('test_*.py')):
            if path.name in ('test_brain.py', 'test_feedback.py'): continue
            tree = ast.parse(path.read_text())
            uses = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == 'rabik'] + \
                   [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Import) and any(a.name == 'rabik' for a in n.names)]
            with self.subTest(path.name):
                self.assertEqual(uses, [])

    def test_rabik_never_rebinds_a_moved_name_at_module_level(self):
        # `ME_FILE = …` in rabik.py's own code (the --selftest block) stores into rabik's namespace only: the facade sees
        # attribute writes, not module-level ones, so brain would keep the real file. Rebind through the owner instead.
        def module_level(nodes):
            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): continue
                yield node
                for field in ('body', 'orelse', 'finalbody', 'handlers'): yield from module_level(getattr(node, field, None) or [])
        stores = [(n.lineno, n.id) for node in module_level(ast.parse((ROOT / 'rabik.py').read_text()).body)
                  if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For, ast.With))
                  for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id in rabik._OWNERS]
        self.assertEqual(stores, [])

    def test_rabik_py_is_only_the_entry_script(self):
        # Its code is the facade, the hooks and the __main__ block; anything else belongs to a brain module.
        tree = ast.parse((ROOT / 'rabik.py').read_text())
        self.assertEqual([n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], ['_Facade'])

    def test_rebound_globals_stay_in_their_module(self):
        # A `global X` its module rebinds at run time would go stale as a copy on the facade: it is not exported, and
        # every reader (and every test patch) goes to its module.
        declared = {name: path.stem for path in MODULES for node in ast.walk(ast.parse(path.read_text()))
                    if isinstance(node, ast.Global) for name in node.names}
        self.assertTrue(declared)
        for name, stem in declared.items():
            with self.subTest(name):
                self.assertNotIn(name, importlib.import_module('brain.' + stem).__all__)
                self.assertFalse(hasattr(rabik, name))

    def test_a_cancel_reaches_every_module(self):
        # STOPPING is rebound when an ask is cancelled; every module reads it as turn.STOPPING.
        with patch.object(brain.turn, 'STOPPING', True), self.assertRaises(InterruptedError):
            brain.hands.hands_call(['state'])

    def test_log_turn_still_falls_back_to_the_last_replay(self):
        # turn sits below skills: it reads the last replay's steps through the hook rabik.py sets
        with patch.object(brain.turn, 'TURN', {}), patch.object(brain.skills.replay, 'ran', ['open -a Notes'], create=True), \
                patch.object(brain.storage, 'append_log') as log:
            brain.turn.log_turn('open notes', 'Done.', time.time())
        self.assertEqual(log.call_args.args[0]['ran'], ['open -a Notes'])

    def test_the_helper_path_is_the_entry_script(self):
        self.assertEqual(brain.paths.ME, str(ROOT / 'rabik.py'))
        self.assertIn(brain.paths.ME, brain.paths.PLACE)


if __name__ == '__main__':
    unittest.main()
