"""The phase messages shown after the version line, from start to end."""
import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import photo_organizer as org
from tests.helpers import Base, exif_jpeg

SCRIPT = Path(__file__).resolve().parent.parent / "photo_organizer.py"


class Phases(Base):
    def lines(self, **kw):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("b.jpg", exif_jpeg("2019:07:05 15:30:12"))
        self.put("clip.avi", b"x")
        self.put(".hidden.jpg", exif_jpeg("2019:07:06 15:30:12"))
        c = self.go(**kw)
        return c, self.stdout.splitlines()

    def index_of(self, lines, prefix):
        found = [i for i, line in enumerate(lines) if line.startswith(prefix)]
        self.assertEqual(len(found), 1, f"{prefix!r} in {lines}")
        return found[0]

    def test_the_phases_come_in_this_order(self):
        _c, lines = self.lines()
        order = [self.index_of(lines, prefix) for prefix in (
            "Starting program with options", "Input folder:", "Output folder:", "Reports folder:",
            "Starting preliminary scan", "Preliminary scan completed", "Starting file handling",
            "Mode:", "CSV report:", "Program end")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(lines[-1], "Program end. See the reports for details.")

    def test_options_show_testrun_yes_and_no(self):
        _c, lines = self.lines(testrun="yes")
        self.assertIn("testrun=yes", lines[self.index_of(lines, "Starting program")])
        self.assertIn("test run", lines[self.index_of(lines, "Starting file handling")])

    def test_options_show_testrun_no(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(testrun="no")
        lines = self.stdout.splitlines()
        first = lines[self.index_of(lines, "Starting program")]
        self.assertIn("testrun=no", first)
        self.assertIn("copy_mode=yes", first)
        self.assertNotIn("test run", lines[self.index_of(lines, "Starting file handling")])

    def test_move_mode_is_shown(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(testrun="no", copy_mode="no")
        self.assertIn("copy_mode=no", self.stdout)

    def test_the_three_folders_are_shown(self):
        c, lines = self.lines()
        self.assertEqual(lines[self.index_of(lines, "Input folder:")].split(":", 1)[1].strip(), str(c["input"]))
        self.assertEqual(lines[self.index_of(lines, "Output folder:")].split(":", 1)[1].strip(), str(c["output"]))
        self.assertEqual(lines[self.index_of(lines, "Reports folder:")].split(":", 1)[1].strip(), str(c["reports_dir"]))

    def test_the_scan_result_counts_files_to_process_and_skipped(self):
        _c, lines = self.lines()
        done = lines[self.index_of(lines, "Preliminary scan completed")]
        self.assertIn("2 file(s) to process", done)
        self.assertIn("2 skipped", done)  # clip.avi and the hidden file
        self.assertNotIn("unreadable", done)

    def test_an_empty_input_folder_still_runs_through_every_phase(self):
        self.go()
        lines = self.stdout.splitlines()
        self.assertIn("0 file(s) to process", lines[self.index_of(lines, "Preliminary scan completed")])
        self.assertEqual(lines[-1], "Program end. See the reports for details.")

    def test_the_old_summary_lines_are_unchanged(self):
        _c, lines = self.lines(testrun="no")
        self.assertTrue(any(line.startswith("Mode: LIVE (copy) | completed=2") for line in lines))

    def test_the_end_line_is_not_printed_when_the_run_is_interrupted(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        c = self.conf()
        out = io.StringIO()
        with mock.patch.object(org, "process_image", side_effect=KeyboardInterrupt), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                org.run(c)
        self.assertNotIn("Program end", out.getvalue())


class Documented(unittest.TestCase):
    def test_every_phase_line_is_described_in_the_readme(self):
        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
        for text in ("Starting program with options: testrun=", "Input folder:", "Output folder:", "Reports folder:",
                     "Starting preliminary scan", "Preliminary scan completed", "Starting file handling",
                     "Program end. See the reports for details."):
            with self.subTest(text):
                self.assertIn(text, readme)


class ConsoleFailure(Base):
    def test_say_never_raises(self):
        for error in (OSError("closed pipe"), ValueError("I/O operation on closed file")):
            with self.subTest(type(error).__name__), mock.patch("builtins.print", side_effect=error):
                org.say("anything")

    def test_a_console_that_fails_during_the_phases_costs_no_result(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        c = self.conf()
        real_print = print

        def picky(*args, **kwargs):
            if str(args[0]).startswith(("Starting", "Input", "Output", "Reports", "Preliminary", "Program end")):
                raise OSError("console gone")
            real_print(*args, **kwargs)

        with mock.patch("builtins.print", picky), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            code = org.run(c)
        self.assertEqual(code, 0)
        self.assertTrue((self.out / "2019_07" / "a.jpg").exists())


class OnTheCommandLine(Base):
    def test_version_line_first_then_the_phases(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.conf()
        result = subprocess.run([sys.executable, str(SCRIPT), "--config", str(self.root / "config.ini")],
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], f"Photo Organizer {org.version_string()}")
        self.assertTrue(lines[1].startswith("Starting program with options: testrun=no"))
        self.assertEqual(lines[-1], "Program end. See the reports for details.")
        self.assertNotIn("\r", result.stdout)  # the progress line is on stderr and only on a terminal


if __name__ == "__main__":
    unittest.main()
