"""reports_folder: the CSV reports go into a folder next to config.ini instead of the program directory."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import photo_organizer as org
from tests.helpers import exif_jpeg

SCRIPT = Path(__file__).resolve().parent.parent / "photo_organizer.py"


class ReportsFolder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.program = self.root / "program"  # where config.ini lives
        self.program.mkdir()
        self.inp, self.out = self.root / "in", self.root / "out"
        self.inp.mkdir()
        (self.inp / "a.jpg").write_bytes(exif_jpeg("2019:07:04 15:30:12"))

    def write(self, behavior="", testrun="no"):
        text = f"[folders]\ninput_folder = {self.inp}\noutput_folder = {self.out}\n[organization]\ntestrun = {testrun}\n[behavior]\n{behavior}\n"
        (self.program / "config.ini").write_text(text, encoding="utf-8")
        return self.program / "config.ini"

    def run_cli(self, config, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--config", str(config)], capture_output=True, text=True,
                              encoding="utf-8", cwd=cwd or self.root, timeout=60)

    def names(self, folder):
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    def test_default_is_a_reports_folder_next_to_the_config_file(self):
        c = org.read_config(self.write())
        self.assertEqual(c["reports_dir"], self.program / "reports")
        self.assertEqual(c["report"], self.program / "reports" / "organizer_report.csv")
        self.assertEqual(c["unknown_csv"], self.program / "reports" / "unknown_files.csv")

    def test_a_run_puts_the_reports_there_and_nothing_else_next_to_the_config(self):
        (self.inp / "clip.avi").write_bytes(b"x")
        result = self.run_cli(self.write(), cwd=self.root)  # started from another folder on purpose
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.names(self.program / "reports"), ["organizer_report.csv", "unknown_files.csv"])
        self.assertEqual(self.names(self.program), ["config.ini", "reports"])
        self.assertEqual([p for p in self.root.glob("*.csv")], [])  # nor in the working directory
        self.assertIn(str(self.program / "reports" / "organizer_report.csv"), result.stdout)
        self.assertIn(str(self.program / "reports" / "unknown_files.csv"), result.stderr)

    def test_the_folder_is_created_including_parents(self):
        c = org.read_config(self.write("reports_folder = logs/2026/november"))
        self.assertEqual(c["reports_dir"], self.program / "logs" / "2026" / "november")
        self.run_cli(self.program / "config.ini")
        self.assertTrue((self.program / "logs" / "2026" / "november" / "organizer_report.csv").is_file())

    def test_an_absolute_folder(self):
        elsewhere = self.root / "elsewhere" / "reports"
        self.run_cli(self.write(f"reports_folder = {elsewhere}"))
        self.assertEqual(self.names(elsewhere), ["organizer_report.csv"])
        self.assertEqual(self.names(self.program), ["config.ini"])

    def test_a_dot_or_an_empty_value_keeps_the_old_location(self):
        for value in (".", "", "./"):
            with self.subTest(repr(value)):
                c = org.read_config(self.write(f"reports_folder = {value}"))
                self.assertEqual(c["report"], self.program / "organizer_report.csv")

    def test_the_file_names_are_configurable_inside_the_folder(self):
        c = org.read_config(self.write("report_csv = run.csv\nunknown_files_csv = other/skipped.csv"))
        self.assertEqual(c["report"], self.program / "reports" / "run.csv")
        self.assertEqual(c["unknown_csv"], self.program / "reports" / "other" / "skipped.csv")

    def test_an_absolute_file_path_ignores_the_folder(self):
        absolute = self.root / "fixed.csv"
        c = org.read_config(self.write(f"report_csv = {absolute}"))
        self.assertEqual(c["report"], absolute)
        self.assertEqual(c["unknown_csv"], self.program / "reports" / "unknown_files.csv")

    def test_an_old_configuration_with_dot_slash_names_lands_in_the_folder(self):
        c = org.read_config(self.write("report_csv = ./organizer_report.csv\nunknown_files_csv = ./unknown_files.csv"))
        self.assertEqual(c["report"], self.program / "reports" / "organizer_report.csv")
        self.assertEqual(c["unknown_csv"], self.program / "reports" / "unknown_files.csv")

    def test_a_test_run_writes_only_the_reports(self):
        result = self.run_cli(self.write(testrun="yes"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.program / "reports" / "organizer_report.csv").is_file())
        self.assertFalse(self.out.exists())

    def test_reports_are_overwritten_each_run_not_accumulated(self):
        config = self.write()
        self.run_cli(config)
        first = (self.program / "reports" / "organizer_report.csv").read_text(encoding="utf-8-sig")
        self.run_cli(config)
        second = (self.program / "reports" / "organizer_report.csv").read_text(encoding="utf-8-sig")
        self.assertEqual(self.names(self.program / "reports"), ["organizer_report.csv"])
        self.assertIn("completed", first)
        self.assertIn("skipped_identical", second)

    def test_a_reports_folder_inside_the_input_folder_is_refused_with_the_option_name(self):
        with self.assertRaises(ValueError) as caught:
            org.read_config(self.write(f"reports_folder = {self.inp / 'reports'}"))
        message = str(caught.exception)
        self.assertIn("report_csv", message)
        self.assertIn("reports_folder", message)
        self.assertIn("inside the input folder", message)

    def test_the_unknown_files_list_can_still_be_elsewhere(self):
        elsewhere = self.root / "unknown.csv"
        org.read_config(self.write(f"unknown_files_csv = {elsewhere}"))  # allowed: outside the input folder

    def test_a_reports_folder_inside_the_output_folder_is_allowed(self):
        c = org.read_config(self.write(f"reports_folder = {self.out / 'reports'}"))
        self.assertEqual(c["reports_dir"], self.out / "reports")

    def test_a_file_where_the_folder_should_be_stops_the_run_before_any_work(self):
        (self.program / "reports").write_text("I am a file", encoding="utf-8")
        result = self.run_cli(self.write())
        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR", result.stderr)
        self.assertFalse(self.out.exists())  # nothing was copied

    def test_the_example_config_documents_the_folder(self):
        example = (Path(__file__).resolve().parent.parent / "config.example.ini").read_text(encoding="utf-8")
        self.assertIn("reports_folder = ./reports", example)
        self.assertIn("report_csv = organizer_report.csv", example)


if __name__ == "__main__":
    unittest.main()
