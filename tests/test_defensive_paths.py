"""Error branches that only trigger when the operating system or the input misbehaves."""
import contextlib
import io
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import photo_organizer as org
from tests.helpers import Base, exif_jpeg, jpeg_bytes, make_tiff


class FakeEntry:
    """A DirEntry stand-in for failures that are hard to provoke with real files."""

    def __init__(self, path, stat_error=False, is_file=True):
        self.path, self.name = str(path), Path(path).name
        self._stat_error, self._is_file = stat_error, is_file

    def is_symlink(self):
        return False

    def stat(self, follow_symlinks=True):
        if self._stat_error:
            raise OSError("stat failed")
        return SimpleNamespace()

    def is_dir(self, follow_symlinks=True):
        return False

    def is_file(self, follow_symlinks=True):
        return self._is_file


class ExifStructure(Base):
    def test_jpeg_segment_with_an_impossible_length(self):
        path = self.put("x.jpg", b"\xff\xd8\xff\xe1\x00\x01")
        self.assertIn("corrupt JPEG segment length", org.read_exif_dates(path)[1])

    def test_ascii_values_of_four_bytes_or_less_are_stored_inline(self):
        tags, _ = org.read_exif_dates(self.put("x.jpg", jpeg_bytes(make_tiff({}, {0x9011: "+2"}))))
        self.assertEqual(tags["OffsetTimeOriginal"], "+2")

    def test_tiff_block_too_short_for_its_own_header(self):
        with self.assertRaisesRegex(org.ExifError, "malformed"):
            org.parse_tiff_dates(b"II*\x00")


class DateFailures(Base):
    def test_unreadable_modification_time_leaves_the_file_undated(self):
        def broken_stat():
            raise OSError("gone")

        fake_path = SimpleNamespace(name="photo.jpg", stat=broken_stat)
        conf = dict(min_year=1990, reject_future=True, use_filename_date=True, use_modify_date=False, use_mtime=True)
        choice = org.choose_date(fake_path, {}, conf, datetime(2026, 10, 21))
        self.assertEqual(choice.source, org.SRC_UNKNOWN)
        self.assertIn("file modification time unusable", choice.notes)

    def test_conversion_that_overflows_falls_back_to_the_recorded_time(self):
        dt = datetime(1, 1, 1, 0, 30)
        self.assertEqual(org.to_basis(dt, timedelta(hours=5), "utc"), dt)

    def test_unsupported_strftime_directive_is_reported_clearly(self):
        with mock.patch.object(org, "datetime") as fake:
            fake.return_value.strftime.side_effect = ValueError("Invalid format string")
            with self.assertRaisesRegex(ValueError, "unsupported date directive"):
                org.validate_rename_pattern("%Q")

    def test_timestamp_out_of_range_is_a_note_not_an_error(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        with mock.patch.object(org, "epoch_of", side_effect=OverflowError("out of range")):
            self.go(change_timestamp="yes")
        row = self.row("a.jpg")
        self.assertEqual(row["status"], "completed")
        self.assertIn("timestamp not set: date out of range", row["details"])


class FileSystemFailures(Base):
    def scan_with(self, entries):
        conf = {"input": self.inp, "skip_hidden": True, "recursive": True, "extensions": {".jpg"}}
        with mock.patch.object(org.os, "scandir", lambda d: contextlib.nullcontext(entries)):
            return [(Path(p).name, status) for p, status, _ in org.scan(conf)]

    def test_entry_that_cannot_be_stated_is_an_error_row(self):
        self.assertEqual(self.scan_with([FakeEntry(self.inp / "x.jpg", stat_error=True)]), [("x.jpg", "error")])

    def test_special_files_are_ignored(self):
        self.assertEqual(self.scan_with([FakeEntry(self.inp / "pipe", is_file=False)]), [])

    def test_index_skips_files_that_vanish_during_the_walk(self):
        self.out.mkdir()
        (self.out / "a.jpg").write_bytes(b"x")
        with mock.patch.object(org.Path, "lstat", side_effect=OSError("vanished")):
            index = org.build_index({"output": self.out, "extensions": {".jpg"}})
        self.assertEqual(index._by_size, {})

    def test_size_of_an_unsupported_file_that_cannot_be_read_is_left_blank(self):
        self.put("clip.mp4", b"video")
        real_stat = Path.stat

        def flaky(self, *args, **kwargs):
            if self.name == "clip.mp4":
                raise OSError("denied")
            return real_stat(self, *args, **kwargs)

        with mock.patch.object(org.Path, "stat", flaky):
            self.go()
        text = (self.root / "unknown_files.csv").read_text(encoding="utf-8-sig")
        self.assertIn("clip.mp4,.mp4,", text)
        self.assertEqual(self.code, 0)

    def test_absurd_number_of_name_collisions_stops_with_a_clear_error(self):
        reserved = {os.path.normcase(str(self.out / "a.jpg"))}
        reserved |= {os.path.normcase(str(self.out / f"a_{n:03d}.jpg")) for n in range(1, 100000)}
        with self.assertRaisesRegex(RuntimeError, "too many name collisions"):
            org.unique_destination(self.out, "a.jpg", reserved)


class WindowsPaths(Base):
    """String handling only, so it can be tested on every system."""

    def test_long_local_path_gets_the_extended_prefix(self):
        long_local = "C:\\" + "a" * 250 + "\\x.jpg"
        self.assertEqual(org._win_path(Path(long_local)), "\\\\?\\" + long_local)

    def test_long_unc_path_gets_the_unc_prefix(self):
        long_unc = "\\\\server\\share\\" + "a" * 250 + "\\x.jpg"
        self.assertEqual(org._win_path(Path(long_unc)), "\\\\?\\UNC\\" + long_unc[2:])

    def test_already_prefixed_and_short_paths_are_unchanged(self):
        prefixed = "\\\\?\\C:\\" + "a" * 250 + "\\x.jpg"
        self.assertEqual(org._win_path(Path(prefixed)), os.fspath(Path(prefixed)))
        self.assertEqual(org._win_path(Path("short.jpg")), "short.jpg")


class MainInProcess(Base):
    def test_dry_run_flag_overrides_the_configuration(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.conf(testrun="no")
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["photo_organizer", "--config", str(self.root / "config.ini"), "--dry-run"]), \
                contextlib.redirect_stdout(out):
            code = org.main()
        self.assertEqual(code, 0)
        self.assertIn("TEST ONLY", out.getvalue())
        self.assertFalse(self.out.exists())

