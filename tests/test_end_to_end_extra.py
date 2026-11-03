"""More end-to-end behaviour: odd file names, failures, reports, and test-run fidelity."""
import os
import shutil
from datetime import datetime
from pathlib import Path
from unittest import mock

import photo_organizer as org
from tests.helpers import BMP, Base, exif_jpeg, jpeg_bytes, png_bytes


class OddFiles(Base):
    def test_unicode_and_spaces_in_names(self):
        name = "Zomer 2019 — café ☀ #1.jpg"
        self.put(name, exif_jpeg("2019:07:04 15:30:12"))
        self.go()
        self.assertEqual(self.row(name)["status"], "completed")
        self.assertTrue((self.out / "2019_07" / name).exists())

    def test_upper_case_extension_is_kept_as_is(self):
        self.put("PHOTO.JPG", exif_jpeg("2019:07:04 15:30:12"))
        self.go()
        self.assertEqual(self.outfiles(), ["2019_07/PHOTO.JPG"])

    def test_zero_byte_image_is_processed_with_a_note(self):
        self.put("empty.jpg", b"", mtime=datetime(2021, 5, 6).timestamp())
        self.go()
        row = self.row("empty.jpg")
        self.assertEqual((row["status"], row["date_source"]), ("completed", org.SRC_MTIME))
        self.assertIn("unrecognised file content", row["details"])

    def test_two_zero_byte_images_count_as_identical(self):
        self.put("a.jpg", b"", mtime=datetime(2021, 5, 6).timestamp())
        self.put("b.jpg", b"", mtime=datetime(2021, 5, 6).timestamp())
        self.go()
        self.assertEqual([self.row("a.jpg")["status"], self.row("b.jpg")["status"]], ["completed", "skipped_identical"])

    def test_very_long_but_valid_file_name(self):
        # Windows allows 259 characters for the whole path (unless long paths are enabled), so there the name has to
        # leave room for the folders in front of it; elsewhere a name may be up to 255 bytes.
        room = 250 - len(str(self.out / "2019_07")) - 1 - len(".jpg")
        length = min(200, room) if os.name == "nt" else 200
        if length < 40:
            self.skipTest("the temporary folder is too deep for this test on this system")
        name = "x" * length + ".jpg"
        self.put(name, exif_jpeg("2019:07:04 15:30:12"))
        self.go()
        self.assertEqual(self.outfiles(), ["2019_07/" + name],
                         f"path length {len(str(self.out / '2019_07' / name))}; report: {[r['details'] for r in self.rows()]}")

    def test_name_with_counter_suffix_already_in_the_input(self):
        self.put("a/IMG_001.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("b/IMG_001.jpg", exif_jpeg("2019:07:04 15:30:13"))
        self.go()
        self.assertEqual(self.outfiles(), ["2019_07/IMG_001.jpg", "2019_07/IMG_001_001.jpg"])


class ReportsAndExitCodes(Base):
    def test_empty_input_folder(self):
        self.go()
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.code, 0)
        self.assertIn("Mode: LIVE (copy)", self.stdout)
        self.assertFalse(self.out.exists())

    def test_report_header_is_the_documented_contract(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go()
        header = (self.root / "report.csv").read_text(encoding="utf-8-sig").splitlines()[0]
        self.assertEqual(header, ",".join(["source", "destination", "date_source", "date_recorded", "date_used",
                                           "action", "status", "details"]))
        self.assertEqual(org.FIELDS, header.split(","))

    def test_report_row_values_for_a_normal_photo(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12", offset="+02:00"))
        self.go()
        row = self.row("a.jpg")
        self.assertEqual(row["date_source"], "exif_datetime_original")
        self.assertEqual(row["date_recorded"], "2019-07-04 15:30:12+02:00")
        self.assertEqual(row["date_used"], "2019-07-04 15:30:12")
        self.assertEqual((row["action"], row["status"]), ("copy", "completed"))
        self.assertEqual(Path(row["destination"]), self.out / "2019_07" / "a.jpg")

    def test_summary_line(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("clip.mp4", b"x")
        self.go()
        self.assertIn("Mode: LIVE (copy) | completed=1, skipped_extension=1", self.stdout)
        self.go(testrun="yes")
        self.assertIn("Mode: TEST ONLY (copy)", self.stdout)

    def test_a_failing_file_does_not_stop_the_run_and_sets_exit_code_1(self):
        self.put("bad.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.put("good.jpg", exif_jpeg("2019:07:05 15:30:12"))
        real = org.read_exif_dates

        def flaky(path):
            if path.name == "bad.jpg":
                raise PermissionError("denied")
            return real(path)

        with mock.patch.object(org, "read_exif_dates", flaky):
            self.go()
        self.assertEqual(self.code, 1)
        self.assertEqual(self.row("good.jpg")["status"], "completed")
        self.assertEqual(self.row("bad.jpg")["status"], "error")
        self.assertIn("PermissionError: denied", self.row("bad.jpg")["details"])
        self.assertEqual(self.outfiles(), ["2019_07/good.jpg"])

    def test_output_path_blocked_by_a_file_is_an_error_row_and_the_original_is_kept(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.out.write_bytes(b"i am a file, not a folder")
        self.go(copy_mode="no")
        self.assertEqual(self.code, 1)
        self.assertEqual(self.row("a.jpg")["status"], "error")
        self.assertTrue((self.inp / "a.jpg").exists())

    def test_unknown_files_csv_is_overwritten_when_new_unknowns_appear_and_kept_otherwise(self):
        self.put("one.mp4", b"1")
        self.go()
        first = (self.root / "unknown_files.csv").read_text(encoding="utf-8-sig")
        self.assertIn("one.mp4", first)
        (self.inp / "one.mp4").unlink()
        self.put("two.pdf", b"2")
        self.go()
        second = (self.root / "unknown_files.csv").read_text(encoding="utf-8-sig")
        self.assertIn("two.pdf", second)
        self.assertNotIn("one.mp4", second)
        (self.inp / "two.pdf").unlink()
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go()
        self.assertEqual((self.root / "unknown_files.csv").read_text(encoding="utf-8-sig"), second)

    def test_only_unsupported_files_still_exit_zero(self):
        self.put("movie.mov", b"x")
        self.go()
        self.assertEqual(self.code, 0)
        self.assertIn("WARNING", self.stderr)

    def test_hidden_unsupported_files_are_not_listed_as_unknown(self):
        self.put(".secret.txt", b"x")
        self.go()
        self.assertFalse((self.root / "unknown_files.csv").exists())


class FileTimes(Base):
    def test_copy_preserves_the_source_modification_time(self):
        self.put("x.bmp", BMP, mtime=1_500_000_000)
        self.go(use_filename_date="no")
        (dest,) = [p for p in self.out.rglob("x.bmp")]
        self.assertEqual(int(dest.stat().st_mtime), 1_500_000_000)

    def test_timestamps_untouched_when_the_option_is_off(self):
        self.put("a.jpg", exif_jpeg("2019:07:04 15:30:12"), mtime=1_500_000_000)
        self.go(change_timestamp="no")
        self.assertEqual(int((self.out / "2019_07" / "a.jpg").stat().st_mtime), 1_500_000_000)


class VerifyOff(Base):
    def test_copy_without_verification_is_still_byte_identical(self):
        data = exif_jpeg("2019:07:04 15:30:12") * 5
        self.put("a.jpg", data)
        self.go(verify="no")
        self.assertEqual((self.out / "2019_07" / "a.jpg").read_bytes(), data)


class TestRunFidelity(Base):
    """A test run must predict exactly what the real run does."""

    def build_mixed_input(self):
        same = exif_jpeg("2019:07:04 15:30:12")
        self.put("a/IMG_0001.jpg", same)
        self.put("b/IMG_0001.jpg", exif_jpeg("2019:07:04 15:30:13"))  # same name, other content
        self.put("c/copy.jpg", same)  # same content, other name
        self.put("d/IMG_20180101_010101.png", png_bytes())  # file-name date
        self.put("d/IMG-20170102-WA0001.jpeg", jpeg_bytes())  # date only
        self.put("e/no_date.bmp", BMP, mtime=datetime(2021, 5, 6).timestamp())
        self.put("e/ancient.jpg", exif_jpeg("1970:01:01 00:00:00"), mtime=0)  # -> unknown bucket
        self.put("f/future.jpg", exif_jpeg("2099:01:01 00:00:00"), mtime=datetime(2020, 2, 2).timestamp())
        self.put("g/tz.jpg", exif_jpeg("2019:12:31 23:30:00", offset="-05:00"))
        self.put("h/clip.mp4", b"video")
        self.put(".hidden/x.jpg", jpeg_bytes())

    def snapshot(self):
        result = []
        for row in self.rows():
            dest = Path(row["destination"]).relative_to(self.out).as_posix() if row["destination"] else ""
            result.append((Path(row["source"]).relative_to(self.inp).as_posix(), dest,
                           "completed" if row["status"] == "planned" else row["status"]))
        return result

    def test_dry_run_and_live_run_agree_in_every_option_combination(self):
        combos = [
            {},
            {"output_folderstructure": "YYYY/MM/DD", "rename_by_date": "%Y%m%d_%H%M%S_{original}"},
            {"output_folderstructure": "YYYY/YYYY-MM", "timezone_mode": "utc", "use_filesystem_mtime": "no"},
            {"duplicate_policy": "rename", "output_folderstructure": "YYYY"},
            {"use_exif_modify_date": "yes", "use_filename_date": "no", "unknown_date_folder": "undated"},
        ]
        self.build_mixed_input()
        for combo in combos:
            with self.subTest(combo):
                self.go(testrun="yes", **combo)
                planned = self.snapshot()
                self.assertFalse(self.out.exists())
                self.go(testrun="no", **combo)
                live = self.snapshot()
                self.assertEqual(planned, live)
                made = sorted(p for _, p, s in live if s == "completed")
                self.assertEqual(self.outfiles(), made)
                shutil.rmtree(self.out)

    def test_dry_run_leaves_every_input_file_untouched(self):
        self.build_mixed_input()
        before = sorted((p.relative_to(self.inp).as_posix(), p.stat().st_size, p.stat().st_mtime)
                        for p in self.inp.rglob("*") if p.is_file())
        self.go(testrun="yes", copy_mode="no", cleanup_empty_folders="yes", change_timestamp="yes")
        after = sorted((p.relative_to(self.inp).as_posix(), p.stat().st_size, p.stat().st_mtime)
                       for p in self.inp.rglob("*") if p.is_file())
        self.assertEqual(before, after)
        self.assertFalse(self.out.exists())


class ManyFiles(Base):
    def test_many_same_size_files_with_some_duplicates(self):
        total, duplicate_every = 120, 10
        for i in range(total):
            base = i - 1 if i % duplicate_every == 0 and i else i  # every 10th repeats the previous content
            content = exif_jpeg(f"2019:07:04 15:{base // 60:02d}:{base % 60:02d}")
            self.put(f"f{i:03d}.jpg", content)
        self.go()
        statuses = [r["status"] for r in self.rows()]
        self.assertEqual(statuses.count("skipped_identical"), total // duplicate_every - 1)
        self.assertEqual(statuses.count("completed"), total - (total // duplicate_every - 1))
        self.assertEqual(self.code, 0)

    def test_second_run_is_idempotent(self):
        for i in range(15):
            self.put(f"f{i}.jpg", exif_jpeg(f"2019:07:04 15:30:{i:02d}"))
        self.go()
        first = self.outfiles()
        self.go()
        self.assertEqual(self.outfiles(), first)
        self.assertEqual({r["status"] for r in self.rows()}, {"skipped_identical"})


class MoveMode(Base):
    def test_move_keeps_exactly_the_skipped_files_in_the_input(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        self.put("a.jpg", data)
        self.put("dup.jpg", data)
        self.put("clip.mp4", b"x")
        self.put(".hidden.jpg", jpeg_bytes())
        self.go(copy_mode="no")
        left = sorted(p.name for p in self.inp.iterdir())
        self.assertEqual(left, [".hidden.jpg", "clip.mp4", "dup.jpg"])
        self.assertEqual(self.outfiles(), ["2019_07/a.jpg"])

    def test_cleanup_reports_removed_folders(self):
        self.put("trip/day1/a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(copy_mode="no", cleanup_empty_folders="yes")
        self.assertIn("Removed 2 empty folder(s)", self.stdout)
        removed = [r for r in self.rows() if r["action"] == "remove_empty_folder"]
        self.assertEqual(sorted(Path(r["source"]).name for r in removed), ["day1", "trip"])

    def test_cleanup_is_not_simulated_in_a_test_run(self):
        self.put("trip/a.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(copy_mode="no", cleanup_empty_folders="yes", testrun="yes")
        self.assertIn("not simulated", self.stdout)
        self.assertTrue((self.inp / "trip" / "a.jpg").exists())


class DuplicatePolicies(Base):
    def test_rename_policy_numbers_every_collision_in_order(self):
        for i, folder in enumerate("abcd"):
            self.put(f"{folder}/IMG.jpg", exif_jpeg("2019:07:04 15:30:12"))
        self.go(duplicate_policy="rename")
        self.assertEqual(self.outfiles(), ["2019_07/IMG.jpg", "2019_07/IMG_001.jpg", "2019_07/IMG_002.jpg",
                                           "2019_07/IMG_003.jpg"])

    def test_skip_identical_details_point_to_the_existing_file(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        self.put("a.jpg", data)
        self.put("z.jpg", data)
        self.go()
        row = self.row("z.jpg")
        self.assertEqual(Path(row["destination"]), self.out / "2019_07" / "a.jpg")
        self.assertIn("identical content already exists", row["details"])

    def test_same_content_in_a_different_date_folder_is_still_skipped(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        (self.out / "old_sorting" / "holiday").mkdir(parents=True)
        (self.out / "old_sorting" / "holiday" / "beach.jpg").write_bytes(data)
        self.put("a.jpg", data)
        self.go()
        self.assertEqual(self.row("a.jpg")["status"], "skipped_identical")
        self.assertEqual(self.outfiles(), ["old_sorting/holiday/beach.jpg"])

    def test_renamed_file_is_recognised_as_duplicate_by_its_content_not_its_new_name(self):
        data = exif_jpeg("2019:07:04 15:30:12")
        self.put("IMG_0001.jpg", data)
        self.go(rename_by_date="%Y%m%d_%H%M%S")
        self.go(rename_by_date="%Y%m%d_%H%M%S")  # second run
        self.assertEqual(self.outfiles(), ["2019_07/20190704_153012.jpg"])


class UnknownDateBucket(Base):
    def test_bucket_files_are_not_renamed_and_ignore_the_folder_structure(self):
        self.put("mystery.png", png_bytes())
        self.go(use_filesystem_mtime="no", output_folderstructure="YYYY/MM/DD", rename_by_date="%Y%m%d_{original}")
        self.assertEqual(self.outfiles(), ["unknown_date/mystery.png"])
        self.assertIn("kept original name", self.row("mystery.png")["details"])
        self.assertIn("no usable date", self.row("mystery.png")["details"])

    def test_bucket_collisions_get_counters(self):
        self.put("a/x.png", png_bytes())
        self.put("b/x.png", png_bytes() + b"\x00")
        self.go(use_filesystem_mtime="no")
        self.assertEqual(self.outfiles(), ["unknown_date/x.png", "unknown_date/x_001.png"])

    def test_rejected_dates_explain_why_the_file_is_in_the_bucket(self):
        self.put("a.jpg", exif_jpeg("2099:01:01 00:00:00"))
        self.go(use_filesystem_mtime="no")
        details = self.row("a.jpg")["details"]
        self.assertIn("DateTimeOriginal 2099-01-01 rejected (in the future)", details)
        self.assertEqual(self.outfiles(), ["unknown_date/a.jpg"])


if __name__ == "__main__":
    import unittest
    unittest.main()
