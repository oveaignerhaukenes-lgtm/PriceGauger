"""Tests for the stable project journal and its GitHub links."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "scripts" / "update_project_changelog.py"
spec = importlib.util.spec_from_file_location("project_changelog", path)
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)


class ProjectChangelogTests(unittest.TestCase):
    def test_links_bot_filter_and_idempotence(self):
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        raw = "\n".join([
            f"{a}\t2026-10-21\tFix URLs | links\tDeveloper",
            f"{b}\t2026-10-21\tdocs: refresh project continuity journal [skip ci]\tgithub-actions[bot]",
            f"{c}\t2026-10-20\tAnother merge\tDeveloper",
        ])
        result = journal.render_journal(raw, "owner/repo")
        self.assertIn(f"https://github.com/owner/repo/commit/{a}", result)
        self.assertIn("Fix URLs \\| links", result)
        self.assertNotIn(b, result)
        self.assertIn(c, result)
        self.assertEqual(result, journal.render_journal(raw, "owner/repo"))

    def test_empty_invalid_and_bounded(self):
        self.assertIn("No matching commits found.", journal.render_journal(""))
        with self.assertRaises(ValueError):
            journal.render_journal("", "repo/../../escape")
        raw = "\n".join(
            f"{n:040x}\t2026-10-21\tCommit {n}\tDeveloper"
            for n in range(1, 52)
        )
        self.assertEqual(len(journal.parse_commits(raw)), 40)


if __name__ == "__main__":
    unittest.main()
