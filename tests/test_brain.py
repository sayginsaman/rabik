"""brain/'s layering rules, which keep rabik.py's compatibility facade and every test patch working while code moves out."""
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
import brain.paths
import brain.prefs
import brain.prompts
import brain.apps
import brain.turn

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
        # The layers depend one way (paths, then prefs and storage, ... meeting, then dictation): a cycle would not fail at
        # import, it would hand one module the other half-built.
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
        original = brain.prefs.pref
        with patch.object(rabik, 'pref', side_effect=lambda key, default: 'pi' if key == 'client' else default):
            self.assertIsNot(brain.prefs.pref, original)
            self.assertEqual(rabik.client(), 'pi')   # brain.prefs.client reads the patched pref
        self.assertIs(brain.prefs.pref, original)
        self.assertIs(rabik.pref, original)

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

    def test_rebound_globals_are_read_live_through_the_facade(self):
        # A `global X` that its module rebinds would go stale as a copy here: the facade reads and writes it in its owner.
        declared = {name: path.stem for path in MODULES for node in ast.walk(ast.parse(path.read_text()))
                    if isinstance(node, ast.Global) for name in node.names}
        self.assertEqual({name: module.__name__.split('.')[-1] for name, module in rabik._LIVE.items()}, declared)
        for name, module in rabik._LIVE.items():
            self.assertNotIn(name, module.__all__)
            self.assertNotIn(name, vars(rabik))
        before = brain.apps._APPS_CACHE
        with patch.object(rabik, '_APPS_CACHE', (0, {'Fixture'})):   # what test_universal does
            self.assertEqual(brain.apps._APPS_CACHE, (0, {'Fixture'}))
            self.assertEqual(rabik._APPS_CACHE, (0, {'Fixture'}))
        self.assertIs(brain.apps._APPS_CACHE, before)
        self.assertFalse(hasattr(rabik, 'no_such_name'))

    def test_a_cancel_lives_in_turn_and_reaches_rabik(self):
        # STOPPING is rebound when an ask is cancelled: rabik reads turn.STOPPING, and so does every brain module.
        with patch.object(brain.turn, 'STOPPING', True), self.assertRaises(InterruptedError):
            self.assertTrue(rabik.STOPPING)
            rabik.hands_call(['state'])

    def test_log_turn_still_falls_back_to_the_last_replay(self):
        # turn sits below skills: it reads the last replay's steps through the hook rabik.py sets
        with patch.object(rabik, 'TURN', {}), patch.object(rabik.replay, 'ran', ['open -a Notes'], create=True), \
                patch.object(rabik, 'append_log') as log:
            rabik.log_turn('open notes', 'Done.', time.time())
        self.assertEqual(log.call_args.args[0]['ran'], ['open -a Notes'])

    def test_the_helper_path_is_the_entry_script(self):
        self.assertEqual(brain.paths.ME, str(ROOT / 'rabik.py'))
        self.assertIn(brain.paths.ME, rabik.PLACE)


if __name__ == '__main__':
    unittest.main()
