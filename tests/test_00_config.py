"""Discovery with -s tests imports modules directly; initialize scratch config first."""
from tests import config
import atticus
import unittest


class ConfigTests(unittest.TestCase):
    def test_import_uses_scratch_config(self):
        self.assertEqual(atticus.DIR, config.name)
