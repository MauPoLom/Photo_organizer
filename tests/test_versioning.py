"""The version number and its creation time: shown at every start, and kept consistent by tools/release.py."""
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import photo_organizer as org
from tests.helpers import Base, exif_jpeg
from tools import release

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "photo_organizer.py"
CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A thing.\n\n## [1.2.3] - 2026-01-02\n\nOlder.\n"


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8", timeout=60)


class Shown(Base):
    def test_version_string_format(self):
        self.assertRegex(org.version_string(), r"^\d+\.\d+\.\d+ \(created \d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC\)$")
        self.assertEqual(org.version_string(), f"{org.__version__} (created {org.__created__} UTC)")

    def test_creation_time_is_a_real_past_moment(self):
        moment = datetime.strptime(org.__created__, release.TIME_FORMAT)
        self.assertGreater(moment.year, 2025)
        self.assertLess(moment, datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1))
        self.assertEqual(release.problems(REPO), [])

    def test_every_run_starts_with_the_version_line(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.conf()
        result = cli("--config", str(self.root / "config.ini"))
        self.assertEqual(result.stdout.splitlines()[0], f"Photo Organizer {org.version_string()}")
        self.assertTrue(result.stdout.splitlines()[1].startswith("Starting program with options"))  # the first phase
        self.assertIn("Mode: LIVE", result.stdout)

    def test_the_line_is_also_there_when_the_configuration_is_wrong(self):
        result = cli("--config", str(self.root / "missing.ini"))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout.strip(), f"Photo Organizer {org.version_string()}")
        self.assertIn("ERROR", result.stderr)

    def test_version_and_help_show_it_once(self):
        version = cli("--version")
        self.assertEqual(version.stdout.strip(), f"photo_organizer.py {org.version_string()}")
        help_text = cli("--help").stdout
        self.assertEqual(help_text.count(org.version_string()), 1)
        self.assertNotIn("Photo Organizer " + org.version_string() + "\nMode", help_text)

    def test_the_test_environment_names_the_creation_time_too(self):
        from tools import environment
        self.assertIn(org.__created__, dict(environment.describe())["Program"])


class ReleaseTool(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "photo_organizer.py").write_text('import sys\n__version__ = "1.2.3"\n__created__ = "2026-01-02 03:04:05"  # old\nx = 1\n', encoding="utf-8")
        (self.root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")

    def run_tool(self, *args):
        return release.main([*args, "--root", str(self.root)])

    def test_bumps(self):
        self.assertEqual([release.bump("1.2.3", p) for p in ("patch", "minor", "major")], ["1.2.4", "1.3.0", "2.0.0"])
        with self.assertRaises(ValueError):
            release.bump("1.0.0rc1", "patch")

    def test_release_stamps_source_and_closes_the_changelog(self):
        self.assertEqual(self.run_tool("minor", "--time", "2026-03-04 05:06:07"), 0)
        source = (self.root / "photo_organizer.py").read_text(encoding="utf-8")
        self.assertIn('__version__ = "1.3.0"', source)
        self.assertIn('__created__ = "2026-03-04 05:06:07"', source)
        self.assertEqual(source.count("__created__"), 1)
        changelog = (self.root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]\n\n## [1.3.0] - 2026-03-04\n\n### Added\n\n- A thing.\n\n## [1.2.3] - 2026-01-02", changelog)
        self.assertEqual(release.problems(self.root, datetime(2026, 3, 5)), [])

    def test_dry_run_changes_nothing(self):
        before = [(self.root / n).read_text(encoding="utf-8") for n in ("photo_organizer.py", "CHANGELOG.md")]
        self.assertEqual(self.run_tool("patch", "--dry-run"), 0)
        self.assertEqual(before, [(self.root / n).read_text(encoding="utf-8") for n in ("photo_organizer.py", "CHANGELOG.md")])

    def test_nothing_to_release_is_refused(self):
        self.assertEqual(self.run_tool("patch", "--time", "2026-03-04 05:06:07"), 0)
        self.assertEqual(self.run_tool("patch", "--time", "2026-03-05 05:06:07"), 2)  # Unreleased is empty now

    def test_set_must_be_newer_and_valid(self):
        for bad in ("1.2.3", "1.0.0", "x.y", "2"):
            self.assertEqual(self.run_tool("set", bad), 2, bad)
        self.assertEqual(self.run_tool("set", "2.0.0rc1", "--time", "2026-03-04 05:06:07"), 0)

    def test_the_creation_line_is_added_when_it_does_not_exist_yet(self):
        text = release.stamp_source('__version__ = "1.0.0"\nx = 1\n', "1.1.0", "2026-03-04 05:06:07")
        self.assertEqual(text.splitlines()[:2], ['__version__ = "1.1.0"', '__created__ = "2026-03-04 05:06:07"  # UTC; when this version was made (written by tools/release.py)'])

    def test_windows_line_endings_are_kept(self):
        changelog = release.close_changelog(CHANGELOG.replace("\n", "\r\n"), "1.3.0", "2026-03-04")
        self.assertNotIn("\n", changelog.replace("\r\n", ""))
        self.assertIn("## [1.3.0] - 2026-03-04", changelog)

    def test_problems_are_found(self):
        (self.root / "photo_organizer.py").write_text('__version__ = "1.2.3"\n__created__ = "2026-01-05 03:04:05"\n', encoding="utf-8")
        self.assertTrue(any("dates 1.2.3 as 2026-01-02" in p for p in release.problems(self.root, datetime(2026, 2, 1))))
        (self.root / "photo_organizer.py").write_text('__version__ = "1.2.4"\n__created__ = "2999-01-02 03:04:05"\n', encoding="utf-8")
        found = " | ".join(release.problems(self.root, datetime(2026, 2, 1)))
        self.assertIn("newest changelog entry is 1.2.3", found)
        self.assertIn("lies in the future", found)
        (self.root / "photo_organizer.py").write_text('__version__ = "1.2.3"\n__created__ = "yesterday"\n', encoding="utf-8")
        self.assertIn("not 'YYYY-MM-DD HH:MM:SS'", " ".join(release.problems(self.root)))

    def test_the_real_repository_passes_the_check(self):
        result = subprocess.run([sys.executable, str(REPO / "tools" / "release.py"), "check"], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"Version {org.__version__}, created {org.__created__} UTC", result.stdout)


class Documented(unittest.TestCase):
    def test_readme_and_contributing_explain_the_system(self):
        for name in ("README.md", "CONTRIBUTING.md"):
            self.assertIn("tools/release.py", (REPO / name).read_text(encoding="utf-8"), name)
        self.assertIn("created", (REPO / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
