"""Regression tests for defects found when 0.3.0 was reviewed critically (fixed in 0.3.1).

Each test names the defect it guards. They were written to fail on the 0.3.0 code first.
"""
import contextlib
import io
import os
import pathlib
import signal
import stat
import struct
import subprocess
import sys
import time
import unittest
from unittest import mock

import photo_organizer as org
from tests.helpers import BMP, Base, box, exif_jpeg, fullbox, iinf_box, infe_box, jpeg_bytes, make_tiff

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "photo_organizer.py"
FTYP = box(b"ftyp", b"heic" + b"\x00" * 4 + b"mif1")


class Deadline:
    """Fail a test that takes too long instead of hanging the whole suite (POSIX only; elsewhere it just measures)."""

    def __init__(self, seconds):
        self.seconds = seconds

    def __enter__(self):
        self.start = time.time()
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, self._expired)
            signal.alarm(self.seconds)
        return self

    def _expired(self, *args):
        raise AssertionError(f"still running after {self.seconds} s: the parser can be made to hang")

    def __exit__(self, *exc):
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
        self.elapsed = time.time() - self.start
        return False


# ---------------------------------------------------------------------------------------------------------
# 1. A path the console cannot display turned a successful run into "exit 2" and lost unknown_files.csv
# ---------------------------------------------------------------------------------------------------------
class ConsoleEncoding(Base):
    def test_run_survives_a_console_that_cannot_show_the_path(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("clip.mp4", b"video")
        reports = self.root / "résumé-☀"
        config = self.root / "config.ini"
        config.write_text(f"[folders]\ninput_folder = {self.inp}\noutput_folder = {self.out}\n[organization]\ntestrun = no\n"
                          f"[behavior]\nreport_csv = {reports / 'report.csv'}\nunknown_files_csv = {reports / 'unknown.csv'}\n",
                          encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="ascii")  # a strict ASCII console, as when output is redirected
        result = subprocess.run([sys.executable, str(SCRIPT), "--config", str(config)], capture_output=True, text=True,
                                env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.out / "2019_07" / "a.jpg").exists())
        self.assertTrue((reports / "unknown.csv").exists())  # 0.3.0 never wrote it
        self.assertIn("\\xe9", result.stdout)  # shown with an escape instead of crashing

    def test_the_streams_are_reconfigured_when_possible(self):
        stream = mock.Mock()
        with mock.patch.object(sys, "stdout", stream), mock.patch.object(sys, "stderr", stream):
            org._safe_console()
        self.assertEqual(stream.reconfigure.call_count, 2)
        stream.reconfigure.assert_called_with(errors="backslashreplace")

    def test_streams_without_reconfigure_are_left_alone(self):
        with mock.patch.object(sys, "stdout", io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
            org._safe_console()  # must not raise


# ---------------------------------------------------------------------------------------------------------
# 2. Crafted files could make the parsers run for minutes (denial of service)
# ---------------------------------------------------------------------------------------------------------
class HostileInput(Base):
    def read(self, data, name="evil.heic"):
        return org.read_exif_dates(self.put(name, data))

    def test_iloc_extents_without_any_fields_do_not_hang(self):
        body = bytes([0x00, 0x00]) + struct.pack(">H", 4000)  # version 1; offset, length, base and index size all 0
        for i in range(4000):
            body += struct.pack(">HHH", i + 1, 0, 0) + struct.pack(">H", 65535)
        meta = fullbox(b"meta", 0, iinf_box([infe_box(1, b"Exif")]) + fullbox(b"iloc", 1, body))
        with Deadline(10) as clock:
            tags, warning = self.read(FTYP + meta)
        self.assertEqual(tags, {})
        self.assertIn("without any fields", warning)
        self.assertLess(clock.elapsed, 2)  # 0.3.0 needed hours for this 32 KB file

    def test_iloc_with_an_enormous_number_of_real_extents_is_refused(self):
        body = bytes([0x44, 0x00]) + struct.pack(">I", 300_000)  # version 2, 4-byte offsets and lengths
        body += (struct.pack(">IHH", 1, 0, 1) + struct.pack(">II", 0, 1)) * 300_000
        meta = fullbox(b"meta", 0, iinf_box([infe_box(1, b"Exif")]) + fullbox(b"iloc", 2, body))
        with Deadline(10) as clock:
            tags, warning = self.read(FTYP + meta)
        self.assertIn("iloc box too large", warning)
        self.assertLess(clock.elapsed, 3)

    def test_a_normal_iloc_is_far_below_the_limit(self):
        # the real iPhone fixture has 51 items; the limit leaves four orders of magnitude of room
        self.assertGreater(org.MAX_ILOC_WORK, 100 * 51 * 2)

    def test_jpeg_with_endless_tiny_segments(self):
        data = b"\xff\xd8" + b"\xff\xe5\x00\x02" * 200_000 + b"\xff\xda"
        with Deadline(10) as clock:
            tags, warning = self.read(data, "evil.jpg")
        self.assertIn("too many segments", warning)
        self.assertLess(clock.elapsed, 2)

    def test_png_with_endless_empty_chunks(self):
        chunk = struct.pack(">I4s", 0, b"tEXt") + b"\x00\x00\x00\x00"
        data = org.PNG_SIGNATURE + chunk * 150_000
        with Deadline(20) as clock:
            tags, warning = self.read(data, "evil.png")
        self.assertIn("too many chunks", warning)
        self.assertLess(clock.elapsed, 5)

    def test_very_long_digit_runs_in_a_file_name(self):
        with Deadline(10) as clock:
            for name in ("1" * 5000, "20" * 2500, "2019" + "07" * 2000, "20190704_" * 500):
                org.date_from_filename(name)
        self.assertLess(clock.elapsed, 2)

    def test_a_legitimate_png_with_many_idat_chunks_still_works(self):
        tiff = make_tiff({}, {0x9003: "2020:01:02 03:04:05"})
        idat = struct.pack(">I4s", 8, b"IDAT") + b"\x00" * 8 + b"\x00" * 4
        data = org.PNG_SIGNATURE + struct.pack(">I4s", 13, b"IHDR") + b"\x00" * 17 + idat * 20_000 \
            + struct.pack(">I4s", len(tiff), b"eXIf") + tiff + b"\x00" * 4
        self.assertEqual(self.read(data, "big.png")[0]["DateTimeOriginal"], "2020:01:02 03:04:05")

    def test_a_legitimate_jpeg_with_a_near_maximum_exif_segment_still_works(self):
        tiff = make_tiff({0x0132: "2019:07:05 08:00:00"}, {0x9003: "2019:07:04 15:30:12"})
        padded = tiff + b"\x00" * (65535 - 2 - 6 - len(tiff))  # the largest APP1 payload a JPEG can hold
        self.assertEqual(self.read(jpeg_bytes(padded), "big.jpg")[0]["DateTimeOriginal"], "2019:07:04 15:30:12")


# ---------------------------------------------------------------------------------------------------------
# 3. A read-only source file made a successful copy fail on Windows and left a temporary file behind
# ---------------------------------------------------------------------------------------------------------
def windows_like_unlink(real_unlink):
    """Windows refuses to delete a file that carries the read-only attribute; this reproduces that rule."""
    def unlink(self, missing_ok=False):
        try:
            if os.stat(self).st_mode & stat.S_IWUSR == 0:
                raise PermissionError(13, "Access is denied (read-only attribute)", str(self))
        except FileNotFoundError:
            pass
        return real_unlink(self, missing_ok=missing_ok)
    return unlink


class ReadOnlySources(Base):
    def read_only_source(self, name="ro.jpg"):
        src = self.put(name, exif_jpeg("2020:01:02 03:04:05"))
        os.chmod(src, stat.S_IREAD)
        self.addCleanup(lambda: os.path.exists(src) and os.chmod(src, stat.S_IWRITE | stat.S_IREAD))
        return src

    def leftovers(self, folder):
        return [p.name for p in folder.iterdir() if p.name.startswith(org.TEMP_PREFIX)]

    def test_copy_on_a_system_that_cannot_delete_read_only_files(self):
        src = self.read_only_source()
        dest = self.out / "ro.jpg"
        self.addCleanup(lambda: os.path.exists(dest) and os.chmod(dest, stat.S_IWRITE | stat.S_IREAD))
        with mock.patch.object(pathlib.Path, "unlink", windows_like_unlink(pathlib.Path.unlink)):
            org.transfer(src, dest, True, True, None)  # 0.3.0: PermissionError from the cleanup of its own temp file
        self.assertEqual(self.leftovers(self.out), [])
        self.assertEqual(dest.read_bytes(), src.read_bytes())

    def test_the_copy_of_a_read_only_file_is_read_only_too(self):
        src = self.read_only_source()
        dest = self.out / "ro.jpg"
        self.addCleanup(lambda: os.path.exists(dest) and os.chmod(dest, stat.S_IWRITE | stat.S_IREAD))
        org.transfer(src, dest, True, True, None)
        self.assertEqual(os.stat(dest).st_mode & stat.S_IWRITE, 0)
        self.assertEqual(self.leftovers(self.out), [])

    def test_move_of_a_read_only_file_removes_the_original(self):
        src = self.read_only_source()
        dest = self.out / "ro.jpg"
        self.addCleanup(lambda: os.path.exists(dest) and os.chmod(dest, stat.S_IWRITE | stat.S_IREAD))
        with mock.patch.object(pathlib.Path, "unlink", windows_like_unlink(pathlib.Path.unlink)):
            org.transfer(src, dest, False, True, None)
        self.assertFalse(src.exists())
        self.assertTrue(dest.exists())
        self.assertEqual(self.leftovers(self.out), [])

    def test_hard_link_fallback_also_leaves_nothing_behind(self):
        src = self.read_only_source()
        dest = self.out / "ro.jpg"
        self.addCleanup(lambda: os.path.exists(dest) and os.chmod(dest, stat.S_IWRITE | stat.S_IREAD))
        with mock.patch.object(pathlib.Path, "unlink", windows_like_unlink(pathlib.Path.unlink)), \
                mock.patch.object(org.os, "link", side_effect=OSError("no hard links")):
            org.transfer(src, dest, True, True, 1_562_247_012)
        self.assertEqual(self.leftovers(self.out), [])
        self.assertEqual(int(dest.stat().st_mtime), 1_562_247_012)
        self.assertEqual(os.stat(dest).st_mode & stat.S_IWRITE, 0)

    def test_whole_run_with_read_only_photos_and_a_timestamp(self):
        src = self.read_only_source("IMG_1.jpg")
        self.addCleanup(lambda: os.path.exists(self.out / "2020_01" / "IMG_1.jpg")
                        and os.chmod(self.out / "2020_01" / "IMG_1.jpg", stat.S_IWRITE | stat.S_IREAD))
        self.go(change_timestamp="yes")
        self.assertEqual(self.row("IMG_1.jpg")["status"], "completed")
        self.assertEqual(self.code, 0)
        self.assertEqual(self.leftovers(self.out / "2020_01"), [])

    def test_a_failing_attribute_restore_is_a_note_not_an_error(self):
        src = self.read_only_source()
        dest = self.out / "ro.jpg"
        self.addCleanup(lambda: os.path.exists(dest) and os.chmod(dest, stat.S_IWRITE | stat.S_IREAD))
        notes = []
        real_chmod = os.chmod

        def picky_chmod(path, mode, *a, **k):
            if str(path) == str(dest):
                raise PermissionError("not allowed here")
            return real_chmod(path, mode, *a, **k)

        with mock.patch.object(org.os, "chmod", picky_chmod):
            org.transfer(src, dest, True, True, None, notes=notes)
        self.assertTrue(dest.exists())
        self.assertTrue(any("read-only state not copied" in n for n in notes))


# ---------------------------------------------------------------------------------------------------------
# 4. Ctrl-C produced a raw traceback and lost the list of unsupported files
# ---------------------------------------------------------------------------------------------------------
class Interrupts(Base):
    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["photo_organizer", "--config", str(self.root / "config.ini")]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = org.main()
        return code, out.getvalue(), err.getvalue()

    def test_ctrl_c_stops_cleanly_and_keeps_what_was_done(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("b.jpg", exif_jpeg("2019:07:05 15:30:12"))
        self.put("0_notes.pdf", b"x")  # sorts first, so it is already known when the interrupt comes
        self.conf()
        real = org.choose_date
        calls = {"n": 0}

        def interrupt_on_second_photo(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt
            return real(*args, **kwargs)

        with mock.patch.object(org, "choose_date", interrupt_on_second_photo):
            code, _out, err = self.run_main()
        self.assertEqual(code, 130)
        self.assertIn("Interrupted", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg"])
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["skipped_extension", "completed"])  # complete rows only
        self.assertTrue((self.root / "unknown_files.csv").exists())  # 0.3.0 lost it

    def test_ctrl_c_during_a_copy_leaves_no_temporary_file(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.conf()
        with mock.patch.object(org, "sha256", side_effect=KeyboardInterrupt):
            code, _out, _err = self.run_main()
        self.assertEqual(code, 130)
        self.assertEqual([p for p in self.out.rglob("*") if p.is_file()], [])
        self.assertTrue((self.inp / "a.jpg").exists())


# ---------------------------------------------------------------------------------------------------------
# 5. Error messages did not say which option was wrong
# ---------------------------------------------------------------------------------------------------------
class OptionNamesInMessages(Base):
    def message(self, text):
        path = self.root / "bad.ini"
        path.write_text(f"[folders]\ninput_folder = {self.inp}\noutput_folder = {self.out}\n{text}", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            org.read_config(path)
        return str(caught.exception)

    def test_yes_no_options(self):
        for section, key in (("organization", "testrun"), ("organization", "copy_mode"), ("dates", "use_filename_date"),
                             ("behavior", "recursive"), ("behavior", "report_skipped")):
            with self.subTest(key):
                self.assertIn(f"[{section}] {key}", self.message(f"[{section}]\n{key} = maybe\n"))

    def test_whole_number(self):
        message = self.message("[dates]\nmin_year = abc\n")
        self.assertIn("[dates] min_year", message)
        self.assertIn("'abc'", message)
        self.assertNotIn("invalid literal", message)


# ---------------------------------------------------------------------------------------------------------
# 6. Thousands of files with the same name took quadratic time
# ---------------------------------------------------------------------------------------------------------
class CollisionScaling(Base):
    def test_numbering_work_grows_linearly(self):
        total = 400
        for i in range(total):
            self.put(f"b{i:04d}/IMG_0001.jpg", exif_jpeg("2019:07:04 15:30:12") + i.to_bytes(4, "big"))
        calls = {"n": 0}
        real = os.path.lexists

        def counting(path):
            calls["n"] += 1
            return real(path)

        with mock.patch.object(org.os.path, "lexists", counting):
            self.go(testrun="yes")
        names = sorted(pathlib.Path(r["destination"]).name for r in self.rows())
        self.assertEqual(names[0], "IMG_0001.jpg")
        self.assertEqual(names[-1], f"IMG_0001_{total - 1:03d}.jpg")
        self.assertEqual(len(set(names)), total)
        self.assertLess(calls["n"], 4 * total)  # 0.3.0 needed about total * total / 2 = 80,000 calls

    def test_numbers_are_still_consecutive_when_other_names_interleave(self):
        for i in range(6):
            self.put(f"x{i}/IMG_1.jpg", exif_jpeg("2019:07:04 15:30:12") + bytes([i]))
            self.put(f"x{i}/IMG_2.jpg", exif_jpeg("2019:07:04 15:30:13") + bytes([i]))
        self.go()
        self.assertEqual(self.outfiles(), sorted(
            [f"2019_07/IMG_{n}{suffix}.jpg" for n in (1, 2) for suffix in ("", "_001", "_002", "_003", "_004", "_005")]))

    def test_hints_never_hand_out_a_taken_name(self):
        hints, reserved = {}, set()
        first = org.unique_destination(self.out, "a.jpg", reserved, hints)
        reserved.add(os.path.normcase(str(first)))
        second = org.unique_destination(self.out, "a.jpg", reserved, hints)
        reserved.add(os.path.normcase(str(second)))
        reserved.add(os.path.normcase(str(self.out / "a_002.jpg")))  # someone else took the next number
        third = org.unique_destination(self.out, "a.jpg", reserved, hints)
        self.assertEqual([first.name, second.name, third.name], ["a.jpg", "a_001.jpg", "a_003.jpg"])

    def test_a_failed_transfer_does_not_make_test_run_and_live_run_disagree(self):
        for folder in "abc":
            self.put(f"{folder}/IMG.jpg", exif_jpeg("2019:07:04 15:30:12") + folder.encode())
        self.go(testrun="yes")
        planned = [pathlib.Path(r["destination"]).name for r in self.rows()]
        real = org.transfer

        def fail_for_b(src, dest, *args, **kwargs):
            if src.parent.name == "b":
                raise OSError("disk full")
            return real(src, dest, *args, **kwargs)

        with mock.patch.object(org, "transfer", fail_for_b):
            self.go(testrun="no")
        live = {pathlib.Path(r["source"]).parent.name: pathlib.Path(r["destination"]).name for r in self.rows()}
        self.assertEqual(planned, ["IMG.jpg", "IMG_001.jpg", "IMG_002.jpg"])
        self.assertEqual(live["c"], planned[2])  # the failed file used up its number, as the test run predicted


# ---------------------------------------------------------------------------------------------------------
# 7. A copy that was published but then reported an error was invisible to duplicate detection
# ---------------------------------------------------------------------------------------------------------
class PublishedButFailed(Base):
    def test_identical_file_is_not_copied_again_after_a_failed_move_cleanup(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        self.put("a.jpg", data)
        self.put("b.jpg", data)
        with mock.patch.object(org, "_delete", side_effect=PermissionError("cannot delete the original")):
            self.go(copy_mode="no")
        self.assertEqual(self.row("a.jpg")["status"], "error")
        self.assertIn("cannot delete the original", self.row("a.jpg")["details"])
        self.assertEqual(self.row("b.jpg")["status"], "skipped_identical")  # 0.3.0 made a second copy, b _001
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg"])
        self.assertTrue((self.inp / "a.jpg").exists())  # nothing was lost

    def test_empty_folders_are_not_removed_for_a_file_that_could_not_be_moved(self):
        self.put("trip/a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        with mock.patch.object(org, "_delete", side_effect=PermissionError("denied")):
            self.go(copy_mode="no", cleanup_empty_folders="yes")
        self.assertTrue((self.inp / "trip" / "a.jpg").exists())


class SummaryCounts(Base):
    def test_removed_folders_are_not_counted_as_completed_files(self):
        self.put("trip/day1/a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(copy_mode="no", cleanup_empty_folders="yes")
        self.assertIn("Mode: LIVE (move) | completed=1\n", self.stdout)
        self.assertEqual(sum(1 for r in self.rows() if r["action"] == "remove_empty_folder"), 2)
        self.assertIn("Removed 2 empty folder(s)", self.stdout)


class TooLongPaths(Base):
    """Found by running the suite on a real Windows machine: a 264-character destination path."""

    def test_the_error_row_explains_the_windows_limit(self):
        self.out = self.root / ("o" * 200) / ("p" * 100)  # a deep output folder: far over 259 characters
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        too_long = OSError(2, "The system cannot find the path specified")
        with mock.patch.object(org, "IS_WINDOWS", True), mock.patch.object(org, "transfer", side_effect=too_long):
            self.go()
        row = self.row("a.jpg")
        self.assertEqual(row["status"], "error")
        self.assertGreater(len(row["destination"]), 259)
        self.assertRegex(row["details"], r"destination path is \d+ characters; Windows allows 259")
        self.assertEqual(self.code, 1)

    def test_no_hint_for_a_short_path_or_another_system(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        with mock.patch.object(org, "IS_WINDOWS", True), mock.patch.object(org, "transfer", side_effect=OSError("disk full")):
            self.go()
        self.assertLess(len(self.row("a.jpg")["destination"]), 259)
        self.assertNotIn("Windows allows", self.row("a.jpg")["details"])
        self.out = self.root / ("o" * 200) / ("p" * 100)
        with mock.patch.object(org, "IS_WINDOWS", False), mock.patch.object(org, "transfer", side_effect=OSError("disk full")):
            self.go()
        self.assertNotIn("Windows allows", self.row("a.jpg")["details"])

    def test_one_file_with_a_too_long_path_does_not_stop_the_others(self):
        # Output folder of about 160 characters. The photo with the 124-character name makes its destination longer than
        # Windows allows (unless long paths are enabled); the photo with the short name stays well below the limit.
        self.out = self.root / ("d" * 110)
        long_name = "a" * 120 + ".jpg"
        self.put(long_name, exif_jpeg("2019:07:04 15:30:12"))
        self.put("short.jpg", exif_jpeg("2019:07:05 15:30:12"))
        self.go()
        self.assertEqual(self.row("short.jpg")["status"], "completed")
        long_row = self.row(long_name)
        self.assertIn(long_row["status"], ("completed", "error"))  # error on Windows without long paths
        if long_row["status"] == "error":
            self.assertIn("Windows allows 259", long_row["details"])
        self.assertEqual(self.code, 1 if long_row["status"] == "error" else 0)
        self.assertEqual([p for p in self.out.rglob("*") if p.name.startswith(org.TEMP_PREFIX)], [])


class SmallerFixes(Base):
    def test_the_module_docstring_no_longer_mentions_external_programs(self):
        self.assertNotIn("shell=True", org.__doc__)

    def test_a_run_of_only_unsupported_files_writes_its_list_before_printing(self):
        self.put("clip.mp4", b"x")
        order = []
        real_print = print

        def watching_print(*args, **kwargs):
            order.append(("print", (self.root / "unknown_files.csv").exists()))
            real_print(*args, file=io.StringIO())

        # The phase messages ("Starting ...") go through say(), which can never raise (see tests/test_phases.py),
        # so they may come first. Everything else, the summary, must still wait until the results are on disk.
        with mock.patch("builtins.print", watching_print), mock.patch.object(org, "say", lambda text: None):
            self.go()
        self.assertTrue(order)
        self.assertTrue(all(exists for _, exists in order), "the list must exist before the summary is printed")

    def test_bmp_still_works_after_the_refactor(self):
        self.put("x.bmp", BMP, mtime=1_500_000_000)
        self.go(use_filename_date="no")
        self.assertEqual(self.row("x.bmp")["status"], "completed")


if __name__ == "__main__":
    unittest.main()
