"""brain/'s layering rules, which keep rabik.py's compatibility facade and every test patch working while code moves out."""
import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import rabik
import brain.paths
import brain.prefs
import brain.prompts

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

    def test_every_moved_name_is_the_same_object_on_the_facade(self):
        for module in (brain.paths, brain.prefs, brain.prompts, rabik.storage, rabik.protocol, rabik.telemetry):
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

    def test_the_helper_path_is_the_entry_script(self):
        self.assertEqual(brain.paths.ME, str(ROOT / 'rabik.py'))
        self.assertIn(brain.paths.ME, rabik.PLACE)


if __name__ == '__main__':
    unittest.main()
