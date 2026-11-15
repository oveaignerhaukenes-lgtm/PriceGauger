"""Ensure the deployed Impulse Catcher experiment is reachable in navigation."""
from pathlib import Path
import unittest

from navigation_config import PAGE_GROUPS


class ImpulseCatcherNavigationTest(unittest.TestCase):
    def test_lab_page_is_a_public_navigation_destination(self):
        matches = [entry for entries in PAGE_GROUPS.values() for entry in entries
                   if entry.get("url_path") == "Impulse_Catcher_Lab"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["page"], "pages/0_Impulse_Catcher_Lab.py")
        self.assertTrue(Path(matches[0]["page"]).is_file())


if __name__ == "__main__":
    unittest.main()
