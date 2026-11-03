"""End-to-end runs of the organizer on real files."""

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

import photo_organizer as org

from tests.helpers import BMP, Base, exif_jpeg, jpeg_bytes, png_bytes


class EndToEnd(Base):
    def test_folder_structures(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        expected = {"YYYY": "2019/a.jpg", "YYYY_MM": "2019_07/a.jpg", "YYYY/MM": "2019/07/a.jpg",
                    "YYYY/YYYY-MM": "2019/2019-07/a.jpg", "YYYY/MM/DD": "2019/07/04/a.jpg"}
        for structure, path in expected.items():
            with self.subTest(structure):
                self.go(output_folderstructure=structure)
                self.assertEqual(self.outfiles(), [path])
                import shutil
                shutil.rmtree(self.out)

    def test_testrun_creates_nothing_but_reports(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(testrun="yes")
        self.assertFalse(self.out.exists())
        self.assertEqual(self.row("a.jpg")["status"], "planned")
        self.assertEqual(self.row("a.jpg")["date_source"], org.SRC_ORIGINAL)

    def test_unknown_date_bucket(self):
        self.put("mystery.png", png_bytes())
        self.go(use_filesystem_mtime="no")
        self.assertEqual(self.outfiles(), ["unknown_date/mystery.png"])
        self.assertEqual(self.row("mystery.png")["date_source"], "unknown")
        import shutil
        shutil.rmtree(self.out)
        self.go(use_filesystem_mtime="no", unknown_date_folder="nodate")
        self.assertEqual(self.outfiles(), ["nodate/mystery.png"])

    def test_mtime_fallback_and_filename_fallback(self):
        self.put("x.bmp", BMP, mtime=datetime(2021, 5, 6, 7).timestamp())
        self.put("IMG_20190704_153012.png", png_bytes())
        self.go()
        self.assertEqual(self.outfiles(), ["2019_07/IMG_20190704_153012.png", "2021_05/x.bmp"])
        self.assertEqual(self.row("x.bmp")["date_source"], org.SRC_MTIME)

    def test_timezone_modes_choose_folder(self):
        self.put("a.jpg", exif_jpeg("2019:07:31 23:30:00", offset="-05:00"))
        self.go(timezone_mode="wallclock")
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg"])
        self.assertEqual(self.row("a.jpg")["date_recorded"], "2019-07-31 23:30:00-05:00")
        import shutil
        shutil.rmtree(self.out)
        self.go(timezone_mode="utc")
        self.assertEqual(self.outfiles(), ["2019_08/a.jpg"])
        self.assertEqual(self.row("a.jpg")["date_used"], "2019-08-01 04:30:00")

    def test_change_timestamp_uses_offset_and_only_capture_dates(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12", offset="+02:00"), mtime=1_600_000_000)
        self.put("IMG_20180101_010101.png", png_bytes(), mtime=1_600_000_000)
        self.go(change_timestamp="yes")
        expected = datetime(2019, 7, 4, 13, 30, 12, tzinfo=timezone.utc).timestamp()
        self.assertEqual(int((self.out / "2019_07" / "a.jpg").stat().st_mtime), int(expected))
        self.assertEqual(int((self.out / "2018_01" / "IMG_20180101_010101.png").stat().st_mtime), 1_600_000_000)
        self.assertEqual((self.inp / "a.jpg").stat().st_mtime, 1_600_000_000)  # original untouched

    def test_rename_by_date(self):
        self.put("IMG_0042.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("20180101_010101_x.png", png_bytes())
        self.put("IMG-20170102-WA0001.jpg", jpeg_bytes())  # date only: keeps name
        self.put("plain.bmp", BMP, mtime=datetime(2021, 5, 6).timestamp())  # mtime: keeps name
        self.go(rename_by_date="%Y%m%d_%H%M%S_{original}")
        self.assertEqual(self.outfiles(), ["2017_01/IMG-20170102-WA0001.jpg", "2018_01/20180101_010101_20180101_010101_x.png",
                                           "2019_07/20190704_153012_IMG_0042.jpg", "2021_05/plain.bmp"])
        self.assertIn("kept original name", self.row("plain.bmp")["details"])

    def test_rename_pattern_collisions_get_counter(self):
        same = exif_jpeg("2019:07:04 15:30:12")
        self.put("a.jpg", same)
        self.put("b.jpg", same + b"\x00")  # different content, same capture second
        self.go(rename_by_date="%Y%m%d_%H%M%S")
        self.assertEqual(self.outfiles(), ["2019_07/20190704_153012.jpg", "2019_07/20190704_153012_001.jpg"])

    def test_same_name_different_content_gets_counter(self):
        self.put("one/IMG.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("two/IMG.jpg", exif_jpeg("2019:07:04 15:30:13"))
        self.put("three/IMG.jpg", exif_jpeg("2019:07:04 15:30:14"))
        self.go()
        self.assertEqual(self.outfiles(), ["2019_07/IMG.jpg", "2019_07/IMG_001.jpg", "2019_07/IMG_002.jpg"])

    def test_identical_content_different_name_is_skipped(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        self.put("a.jpg", data)
        self.put("copy of a.jpg", data)  # unsupported extension -> not touched
        self.put("sub/b.jpg", data)
        self.go()
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg"])
        self.assertEqual(self.row("b.jpg")["status"], "skipped_identical")
        self.assertTrue((self.inp / "sub" / "b.jpg").exists())
        self.go()  # second run: everything already present
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg"])

    def test_identical_found_in_previous_output_even_in_other_folder(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        (self.out / "elsewhere").mkdir(parents=True)
        (self.out / "elsewhere" / "old_name.jpg").write_bytes(data)
        self.put("new.jpg", data)
        self.go()
        self.assertEqual(self.outfiles(), ["elsewhere/old_name.jpg"])

    def test_testrun_plans_duplicates_like_live_run(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        self.put("a.jpg", data)
        self.put("b.jpg", data)
        self.put("c.jpg", exif_jpeg("2019:07:04 15:30:13"))
        self.go(testrun="yes")
        self.assertEqual([self.row(n)["status"] for n in ("a.jpg", "b.jpg", "c.jpg")],
                         ["planned", "skipped_identical", "planned"])

    def test_rename_policy_never_compares_content(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        self.put("a.jpg", data)
        self.put("sub/a.jpg", data)
        self.go(duplicate_policy="rename")
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg", "2019_07/a_001.jpg"])

    def test_move_deletes_source_only_after_success(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(copy_mode="no")
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg"])
        self.assertFalse((self.inp / "a.jpg").exists())

    def test_move_identical_keeps_original(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        self.put("a.jpg", data)
        self.put("b.jpg", data)
        self.go(copy_mode="no")
        self.assertEqual([p.name for p in self.inp.iterdir()], ["b.jpg"])

    def test_cleanup_empty_folders(self):
        self.put("trip/day1/a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("trip/day2/b.jpg", exif_jpeg("2019:07:05 15:30:12"))
        self.put("trip/day2/notes.txt", b"keep me")
        (self.inp / "never_had_photos").mkdir()
        self.go(copy_mode="no", cleanup_empty_folders="yes")
        self.assertFalse((self.inp / "trip" / "day1").exists())
        self.assertTrue((self.inp / "trip" / "day2" / "notes.txt").exists())
        self.assertTrue((self.inp / "never_had_photos").exists())
        self.assertTrue(self.inp.exists())
        self.assertEqual([r["status"] for r in self.rows() if r["action"] == "remove_empty_folder"], ["completed"])

    def test_cleanup_off_by_default_and_never_in_copy_mode(self):
        self.put("trip/a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(copy_mode="no")
        self.assertTrue((self.inp / "trip").is_dir())
        self.put("trip2/a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(copy_mode="yes", cleanup_empty_folders="yes")
        self.assertTrue((self.inp / "trip2" / "a.jpg").exists())

    def test_skipped_files_reported_and_counted(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("clip.mp4", b"video")
        self.put("noext", b"x")
        self.put(".hidden.jpg", jpeg_bytes())
        self.put(".git/inside.jpg", jpeg_bytes())
        self.go()
        statuses = {Path(r["source"]).name: r["status"] for r in self.rows()}
        self.assertEqual(statuses, {"a.jpg": "completed", "clip.mp4": "skipped_extension",
                                    "noext": "skipped_extension", ".hidden.jpg": "skipped_hidden",
                                    ".git": "skipped_hidden"})
        self.assertIn("skipped_extension=2", self.stdout)
        self.assertIn("skipped_hidden=2", self.stdout)

    def test_report_skipped_no(self):
        self.put("clip.mp4", b"video")
        self.put(".hidden.jpg", jpeg_bytes())
        self.go(report_skipped="no")
        self.assertEqual(self.rows(), [])
        self.assertTrue((self.root / "unknown_files.csv").exists())  # warning file is independent

    def test_hidden_not_skipped_when_disabled(self):
        self.put(".hidden.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(skip_hidden="no")
        self.assertEqual(self.outfiles(), ["2019_07/.hidden.jpg"])

    def test_unknown_files_csv_and_warning(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("clip.MP4", b"12345")
        self.put("deep/doc.pdf", b"123")
        self.go()
        self.assertIn("WARNING: 2 file(s) with unsupported types", self.stderr)
        self.assertIn("unknown_files.csv", self.stderr)
        import csv
        with (self.root / "unknown_files.csv").open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(sorted((Path(r["path"]).name, r["extension"], r["size_bytes"]) for r in rows),
                         [("clip.MP4", ".mp4", "5"), ("doc.pdf", ".pdf", "3")])
        self.assertEqual(self.code, 0)  # unknown files warn, they are not errors

    def test_no_unknown_files_no_csv_no_warning(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go()
        self.assertFalse((self.root / "unknown_files.csv").exists())
        self.assertEqual(self.stderr, "")

    def test_non_recursive(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("sub/b.jpg", exif_jpeg("2019:07:05 15:30:12"))
        self.go(recursive="no")
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg"])

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_symlinks_skipped(self):
        real = self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        try:
            os.symlink(real, self.inp / "link.jpg")
            os.symlink(self.inp, self.inp / "loop", target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation not permitted")
        self.go()
        self.assertEqual(self.row("link.jpg")["status"], "skipped_symlink")
        self.assertEqual(self.row("loop")["status"], "skipped_symlink")
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg"])

    def test_corrupt_file_still_organized_with_note(self):
        self.put("IMG_20190704_153012.jpg", exif_jpeg("2019:07:04 15:30:12")[:40])
        self.go()
        r = self.row("IMG_20190704_153012.jpg")
        self.assertEqual((r["status"], r["date_source"]), ("completed", org.SRC_FILENAME))
        self.assertIn("EXIF unreadable", r["details"])

    def test_no_temp_files_left_behind(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go()
        self.assertFalse(list(self.out.rglob(org.TEMP_PREFIX + "*")))

    def test_copy_is_byte_identical(self):
        data = exif_jpeg("2019:07:04 15:30:12") * 3
        self.put("a.jpg", data)
        self.go()
        self.assertEqual((self.out / "2019_07" / "a.jpg").read_bytes(), data)
