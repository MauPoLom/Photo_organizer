"""Command line behaviour, exit codes and the helper script under tools/."""
import contextlib
import io
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import photo_organizer as org
from tests.helpers import Base, exif_jpeg, heic_bytes, make_tiff

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "photo_organizer.py"


def cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          cwd=cwd, encoding="utf-8", timeout=60)


class Basics(Base):
    def test_version(self):
        result = cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn(org.__version__, result.stdout)

    def test_help_lists_the_two_options_and_the_requirements_note(self):
        result = cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--config", result.stdout)
        self.assertIn("--dry-run", result.stdout)
        self.assertIn("REQUIREMENTS", result.stdout)
        self.assertNotIn("--input", result.stdout)  # deliberately no path overrides

    def test_unknown_argument_is_a_usage_error(self):
        result = cli("--nonsense")
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr.lower())

    def test_module_execution(self):
        result = subprocess.run([sys.executable, "-m", "photo_organizer", "--version"], capture_output=True,
                                text=True, cwd=REPO, timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertIn(org.__version__, result.stdout)


class ExitCodes(Base):
    def config_file(self, **kw):
        self.conf(**kw)
        return str(self.root / "config.ini")

    def test_success_is_zero(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        result = cli("--config", self.config_file())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.out / "2019_07" / "a.jpg").exists())
        self.assertIn("Mode: LIVE (copy) | completed=1", result.stdout)

    def test_missing_config_is_two(self):
        result = cli("--config", str(self.root / "nope.ini"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Config file not found", result.stderr)
        self.assertIn("config.example.ini", result.stderr)

    def test_default_config_name_is_config_ini_in_the_working_directory(self):
        result = cli(cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("config.ini", result.stderr)

    def test_invalid_config_is_two_without_a_traceback(self):
        path = self.config_file()
        text = Path(path).read_text(encoding="utf-8")
        Path(path).write_text(text.replace("[behavior]", "[behavior]\nduplicate_policy = nonsense"), encoding="utf-8")
        result = cli("--config", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_failed_file_is_one(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.out.write_bytes(b"a file where the output folder should be")
        result = cli("--config", self.config_file())
        self.assertEqual(result.returncode, 1)
        self.assertIn("error=1", result.stdout)

    def test_unsupported_files_only_warn(self):
        self.put("clip.mp4", b"x")
        result = cli("--config", self.config_file())
        self.assertEqual(result.returncode, 0)
        self.assertIn("WARNING", result.stderr)
        self.assertIn("unknown_files.csv", result.stderr)


class DryRunFlag(Base):
    def test_flag_forces_a_test_run_even_when_the_config_says_live(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.conf(testrun="no")
        result = cli("--config", str(self.root / "config.ini"), "--dry-run")
        self.assertEqual(result.returncode, 0)
        self.assertIn("TEST ONLY", result.stdout)
        self.assertFalse(self.out.exists())

    def test_without_the_flag_the_config_decides(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.conf(testrun="yes")
        result = cli("--config", str(self.root / "config.ini"))
        self.assertIn("TEST ONLY", result.stdout)
        self.assertFalse(self.out.exists())


class InProcessMain(Base):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["photo_organizer", *args]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = org.main()
        return code, out.getvalue(), err.getvalue()

    def test_main_returns_codes_instead_of_raising(self):
        self.conf()
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.assertEqual(self.run_main("--config", str(self.root / "config.ini"))[0], 0)
        self.assertEqual(self.run_main("--config", str(self.root / "missing.ini"))[0], 2)

    def test_version_flag_exits_through_argparse(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main("--version")
        self.assertEqual(caught.exception.code, 0)


class InspectTool(Base):
    TOOL = REPO / "tools" / "inspect_exif.py"

    def inspect(self, *args):
        return subprocess.run([sys.executable, str(self.TOOL), *map(str, args)], capture_output=True, text=True,
                              encoding="utf-8", timeout=60)

    def test_heic_structure_tags_and_date(self):
        tiff = make_tiff({}, {0x9003: "2019:07:04 15:30:12", 0x9011: "+02:00"})
        path = self.put("IMG_0001.HEIC", heic_bytes(tiff))
        result = self.inspect(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("ftyp brand b'heic'", "item 2: type 'Exif'", "iloc version 1", "'DateTimeOriginal'",
                         "date used : 2019-07-04 15:30:12+02:00", "exif_datetime_original"):
            self.assertIn(expected, result.stdout)

    def test_jpeg_and_missing_file(self):
        path = self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        result = self.inspect(path, self.root / "missing.jpg")
        self.assertEqual(result.returncode, 1)
        self.assertIn("container : JPEG", result.stdout)
        self.assertIn("cannot read", result.stdout)

    def test_warnings_and_notes_are_shown(self):
        path = self.put("IMG_20190704_153012.heic", heic_bytes(make_tiff({}, {0x9003: "2099:01:01 00:00:00"})))
        result = self.inspect(path)
        self.assertIn("rejected (in the future)", result.stdout)
        self.assertIn("source: filename", result.stdout)

    def test_help_and_no_arguments(self):
        for args in ((), ("--help",)):
            result = self.inspect(*args)
            self.assertEqual(result.returncode, 0)
            self.assertIn("Show what Photo Organizer reads", result.stdout)

    def test_a_large_file_is_only_read_at_the_start(self):
        tiff = make_tiff({}, {0x9003: "2019:07:04 15:30:12"})
        path = self.put("big.heic", heic_bytes(tiff) + b"\x00" * (24 * 1024 * 1024))
        started = time.time()
        result = self.inspect(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("item 2: type 'Exif'", result.stdout)
        self.assertLess(time.time() - started, 20)

    def test_garbage_file_does_not_crash_the_tool(self):
        path = self.put("junk.heic", b"\x00\x00\x00\x20ftypxxxx" + b"\xff" * 40)
        result = self.inspect(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning", result.stdout)


class WindowsCheckScript(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "on Windows this script performs the real check")
    def test_refuses_politely_outside_windows(self):
        result = subprocess.run([sys.executable, str(REPO / "tools" / "check_windows_creation_time.py")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Windows", result.stdout)

    @unittest.skipUnless(os.name == "nt", "needs Windows")
    def test_real_check_passes_on_windows(self):
        result = subprocess.run([sys.executable, str(REPO / "tools" / "check_windows_creation_time.py")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
