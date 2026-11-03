"""Tests built on files that came from real phones (see tests/fixtures/README.md).

The fixtures keep the real file structure and the date fields; everything else (image data, camera and
lens details, maker notes, vendor debug blobs) was removed or zeroed.
"""
import random
import shutil
import struct
import unittest
from datetime import datetime, timezone
from pathlib import Path

import photo_organizer as org
from tests.helpers import Base

FIXTURES = Path(__file__).resolve().parent / "fixtures"
IPHONE = "IMG_9347.HEIC"
ANDROID = "IMG20260715143429.jpg"
REENCODED = "IMG_20210727_133442.jpg"
SAMSUNG = "20260822_185518.jpg"

IPHONE_TAGS = {"DateTime": "2024:12:05 14:13:07", "DateTimeOriginal": "2024:12:05 14:13:07",
               "DateTimeDigitized": "2024:12:05 14:13:07", "OffsetTime": "+02:00",
               "OffsetTimeOriginal": "+02:00", "OffsetTimeDigitized": "+02:00"}
ANDROID_TAGS = {"DateTime": "2026:07:15 14:34:29", "DateTimeOriginal": "2026:07:15 14:34:29",
                "DateTimeDigitized": "2026:07:15 14:34:29", "OffsetTimeOriginal": "+02:00"}
SAMSUNG_TAGS = {"DateTime": "2026:08:22 18:55:18", "DateTimeOriginal": "2026:08:22 18:55:18",
                "DateTimeDigitized": "2026:08:22 18:55:18", "OffsetTime": "-04:00", "OffsetTimeOriginal": "-04:00"}
IFD0_ALLOWED = {0x0132, 0x8769}  # DateTime and the pointer to the Exif sub-IFD
EXIF_ALLOWED = {0x9003, 0x9004, 0x9010, 0x9011, 0x9012, 0x9290, 0x9291, 0x9292}  # dates, offsets, sub-seconds


class FixtureBase(Base):
    def fixture(self, name, as_name=None, mtime=None):
        target = self.inp / (as_name or name)
        shutil.copy(FIXTURES / name, target)
        if mtime is not None:
            import os
            os.utime(target, (mtime, mtime))
        return target

    def raw(self, name):
        return (FIXTURES / name).read_bytes()


class IPhoneHeic(FixtureBase):
    def test_tags(self):
        self.assertEqual(org.read_exif_dates(self.fixture(IPHONE)), (IPHONE_TAGS, ""))

    def test_real_world_structure(self):
        data = self.raw(IPHONE)
        self.assertEqual(struct.unpack_from(">I4s", data, 0)[1], b"ftyp")
        self.assertEqual(data[8:12], b"heic")
        # the 'mdat' box of a real iPhone file uses the 64-bit size form
        self.assertEqual(struct.unpack_from(">I4sQ", data, 3403), (1, b"mdat", 907360))
        meta = data[36 + 8:36 + 3367]
        parts = {kind: meta[start:end] for kind, start, end in org._iter_boxes(meta, 4)}
        self.assertEqual(sorted(parts), [b"dinf", b"hdlr", b"idat", b"iinf", b"iloc", b"iprp", b"iref", b"pitm"])
        items = org._heif_items(parts[b"iinf"])
        kinds = {}
        for _, item_type in items:
            kinds[item_type] = kinds.get(item_type, 0) + 1
        self.assertEqual(kinds, {b"hvc1": 49, b"grid": 1, b"Exif": 1})
        locations = org._heif_locations(parts[b"iloc"])
        self.assertEqual(parts[b"iloc"][0], 1)  # iloc version 1
        self.assertEqual(locations[51], (0, 0, [(13880, 2266)]))  # Exif: a plain file offset
        self.assertEqual(locations[49], (1, 0, [(0, 8)]))  # grid descriptor: construction method 1 (idat)

    def test_file_contains_no_image_data_after_the_exif_item(self):
        self.assertEqual(len(self.raw(IPHONE)), 13880 + 2266)

    def test_sorted_by_exif_date(self):
        self.fixture(IPHONE)
        self.go()
        self.assertEqual(self.outfiles(), ["2024_12/IMG_9347.HEIC"])
        row = self.row(IPHONE)
        self.assertEqual((row["date_source"], row["date_recorded"]), (org.SRC_ORIGINAL, "2024-12-05 14:13:07+02:00"))

    def test_rename_timezone_and_timestamp_options(self):
        self.fixture(IPHONE)
        self.go(rename_by_date="%Y%m%d_%H%M%S_{original}", timezone_mode="utc", change_timestamp="yes")
        self.assertEqual(self.outfiles(), ["2024_12/20241205_121307_IMG_9347.HEIC"])
        expected = datetime(2024, 12, 5, 12, 13, 7, tzinfo=timezone.utc).timestamp()
        self.assertEqual(int((self.out / "2024_12" / "20241205_121307_IMG_9347.HEIC").stat().st_mtime), int(expected))

    def test_copy_is_byte_identical(self):
        self.fixture(IPHONE)
        self.go()
        self.assertEqual((self.out / "2024_12" / IPHONE).read_bytes(), self.raw(IPHONE))

    def test_damage_anywhere_in_the_file_is_handled(self):
        data = self.raw(IPHONE)
        cut_points = set(range(0, len(data), 61)) | set(range(3395, 3425)) | set(range(13870, 13900))
        for n in sorted(cut_points | {len(data) - 1, len(data)}):
            tags, warning = org.read_exif_dates(self.put("cut.heic", data[:n]))
            self.assertIsInstance(tags, dict, f"prefix {n}")
            self.assertIsInstance(warning, str, f"prefix {n}")

    def test_random_corruption_of_the_real_structure_never_raises(self):
        rng = random.Random(20261024)
        data = self.raw(IPHONE)
        for i in range(400):
            damaged = bytearray(data)
            for _ in range(rng.randint(1, 8)):
                # concentrate on the structural part: ftyp/meta/mdat header and the Exif item
                index = rng.randrange(0, 3500) if rng.random() < 0.7 else rng.randrange(13870, 14100)
                damaged[index] = rng.randrange(256)
            tags, warning = org.read_exif_dates(self.put(f"c{i}.heic", bytes(damaged)))
            self.assertIsInstance(tags, dict)
            self.assertIsInstance(warning, str)


class AndroidJpeg(FixtureBase):
    def segments(self):
        data, pos, found = self.raw(ANDROID), 2, []
        while data[pos] == 0xFF and data[pos + 1] != 0xDA:
            length = struct.unpack_from(">H", data, pos + 2)[0]
            found.append((data[pos + 1], length, data[pos + 4:pos + 4 + 14]))
            pos += 2 + length
        return found

    def test_tags(self):
        self.assertEqual(org.read_exif_dates(self.fixture(ANDROID)), (ANDROID_TAGS, ""))

    def test_real_world_segment_layout(self):
        layout = [(marker, length) for marker, length, _ in self.segments()]
        self.assertEqual(layout[0][0], 0xE1)  # Exif first
        self.assertIn(0xE2, [m for m, _ in layout])  # ICC profile
        self.assertIn((0xE4, 65535), layout)  # a maximum-length vendor segment must be skipped correctly
        self.assertTrue(any(payload.startswith(b"QTI Debug Meta") for _, _, payload in self.segments()))
        self.assertEqual(self.raw(ANDROID)[-2:], b"\xff\xd9")

    def test_big_endian_exif_after_vendor_segments_is_found_regardless(self):
        data = self.raw(ANDROID)
        self.assertEqual(data[6:10], b"Exif")
        self.assertEqual(data[12:14], b"MM")  # big-endian TIFF, as written by this phone

    def test_sorted_with_offset_and_timestamp(self):
        self.fixture(ANDROID)
        self.go(change_timestamp="yes", rename_by_date="%Y%m%d_%H%M%S")
        self.assertEqual(self.outfiles(), ["2026_07/20260715_143429.jpg"])
        expected = datetime(2026, 7, 15, 12, 34, 29, tzinfo=timezone.utc).timestamp()
        self.assertEqual(int((self.out / "2026_07" / "20260715_143429.jpg").stat().st_mtime), int(expected))
        self.assertEqual(self.row(ANDROID)["date_source"], org.SRC_ORIGINAL)

    def test_exif_wins_over_a_conflicting_file_name(self):
        self.fixture(ANDROID, as_name="IMG20200101000000.jpg")
        self.go()
        self.assertEqual(self.outfiles(), ["2026_07/IMG20200101000000.jpg"])

    def test_every_prefix_is_handled(self):
        data = self.raw(ANDROID)
        for n in sorted(set(range(0, 1500)) | set(range(0, len(data), 997)) | {len(data)}):
            tags, warning = org.read_exif_dates(self.put("cut.jpg", data[:n]))
            self.assertIsInstance(tags, dict, f"prefix {n}")


class SamsungJpeg(FixtureBase):
    """Samsung Galaxy A57: little-endian Exif, negative UTC offset, restart interval, vendor trailer after the image."""

    def test_tags(self):
        self.assertEqual(org.read_exif_dates(self.fixture(SAMSUNG)), (SAMSUNG_TAGS, ""))

    def test_real_world_layout(self):
        data = self.raw(SAMSUNG)
        self.assertEqual(data[12:14], b"II")  # little-endian TIFF (the other fixtures are big-endian)
        self.assertIn(b"\xff\xdd\x00\x04\x00\xfa", data)  # DRI: restart interval 250
        segments, pos = [], 2
        while data[pos] == 0xFF and data[pos + 1] != 0xDA:
            length = struct.unpack_from(">H", data, pos + 2)[0]
            segments.append((data[pos + 1], length))
            pos += 2 + length
        self.assertEqual([m for m, _ in segments][:3], [0xE1, 0xE2, 0xE4])  # Exif, ICC profile, vendor blob
        self.assertIn((0xE4, 38971), segments)

    def test_vendor_trailer_after_the_image_is_ignored(self):
        data = self.raw(SAMSUNG)
        end = data.rindex(b"\xff\xd9")
        trailer = data[end + 2:]
        self.assertEqual(len(trailer), 221)
        self.assertTrue(trailer.endswith(b"SEFT"))
        self.assertEqual(trailer[:-12], b"\x00" * 209)  # content removed, closing structure kept

    def test_negative_offset_is_applied(self):
        self.fixture(SAMSUNG)
        self.go(rename_by_date="%Y%m%d_%H%M%S", timezone_mode="utc", change_timestamp="yes")
        self.assertEqual(self.outfiles(), ["2026_08/20260822_225518.jpg"])
        expected = datetime(2026, 8, 22, 22, 55, 18, tzinfo=timezone.utc).timestamp()
        self.assertEqual(int((self.out / "2026_08" / "20260822_225518.jpg").stat().st_mtime), int(expected))
        self.assertEqual(self.row(SAMSUNG)["date_recorded"], "2026-08-22 18:55:18-04:00")

    def test_wall_clock_mode_keeps_the_camera_time(self):
        self.fixture(SAMSUNG)
        self.go(rename_by_date="%Y%m%d_%H%M%S")
        self.assertEqual(self.outfiles(), ["2026_08/20260822_185518.jpg"])

    def test_a_late_evening_photo_crosses_midnight_in_utc(self):
        data = self.raw(SAMSUNG).replace(b"2026:08:22 18:55:18", b"2026:08:22 21:15:00")
        self.put(SAMSUNG, data)
        self.go(output_folderstructure="YYYY/MM/DD", timezone_mode="utc")
        self.assertEqual(self.outfiles(), ["2026/08/23/" + SAMSUNG])  # 21:15 at -04:00 is 01:15 UTC the next day

    def test_every_prefix_is_handled(self):
        data = self.raw(SAMSUNG)
        for n in sorted(set(range(0, 700)) | set(range(0, len(data), 499)) | {len(data) - 1, len(data)}):
            tags, warning = org.read_exif_dates(self.put("cut.jpg", data[:n]))
            self.assertIsInstance(tags, dict, f"prefix {n}")


class ReencodedJpegWithoutExif(FixtureBase):
    def test_no_tags_and_no_warning(self):
        self.assertEqual(org.read_exif_dates(self.fixture(REENCODED)), ({}, ""))

    def test_file_name_date_is_used(self):
        self.fixture(REENCODED)
        self.go()
        row = self.row(REENCODED)
        self.assertEqual((row["date_source"], row["date_used"]), (org.SRC_FILENAME, "2021-07-27 13:34:42"))
        self.assertEqual(self.outfiles(), ["2021_07/IMG_20210727_133442.jpg"])

    def test_without_a_dated_name_the_modification_time_is_used(self):
        self.fixture(REENCODED, as_name="photo.jpg", mtime=datetime(2020, 3, 4, 5).timestamp())
        self.go()
        self.assertEqual(self.row("photo.jpg")["date_source"], org.SRC_MTIME)
        self.assertEqual(self.outfiles(), ["2020_03/photo.jpg"])

    def test_strict_mode_parks_it_in_the_unknown_date_folder(self):
        self.fixture(REENCODED, as_name="photo.jpg", mtime=datetime(2020, 3, 4, 5).timestamp())
        self.go(use_filename_date="no", use_filesystem_mtime="no")
        self.assertEqual(self.outfiles(), ["unknown_date/photo.jpg"])


class AllTogether(FixtureBase):
    def test_one_run_over_all_fixtures(self):
        for name in (IPHONE, ANDROID, REENCODED, SAMSUNG):
            self.fixture(name)
        self.go(output_folderstructure="YYYY/MM/DD", rename_by_date="%Y%m%d_%H%M%S_{original}")
        self.assertEqual(self.outfiles(), [
            "2021/07/27/20210727_133442_IMG_20210727_133442.jpg",
            "2024/12/05/20241205_141307_IMG_9347.HEIC",
            "2026/07/15/20260715_143429_IMG20260715143429.jpg",
            "2026/08/22/20260822_185518_20260822_185518.jpg",
        ])
        self.assertEqual(self.code, 0)

    def test_test_run_predicts_the_same(self):
        for name in (IPHONE, ANDROID, REENCODED, SAMSUNG):
            self.fixture(name)
        self.go(testrun="yes")
        planned = sorted((Path(r["source"]).name, Path(r["destination"]).relative_to(self.out).as_posix())
                         for r in self.rows())
        shutil.rmtree(self.out, ignore_errors=True)
        self.go(testrun="no")
        live = sorted((Path(r["source"]).name, Path(r["destination"]).relative_to(self.out).as_posix())
                      for r in self.rows())
        self.assertEqual(planned, live)


class FixturesStayAnonymous(FixtureBase):
    """Regression guard: the fixtures may only contain date fields, never camera, lens, GPS or image data."""

    def ifd_tags(self, tiff):
        endian = "<" if tiff[:2] == b"II" else ">"
        ifd0 = org._read_ifd(tiff, endian, struct.unpack_from(endian + "I", tiff, 4)[0])
        pointer = ifd0[0x8769]
        sub = org._read_ifd(tiff, endian, struct.unpack_from(endian + "I", tiff, pointer[2])[0])
        return set(ifd0), set(sub)

    def test_exif_blocks_contain_only_date_tags(self):
        with (FIXTURES / IPHONE).open("rb") as f:
            iphone = org._tiff_from_heif(f)
        with (FIXTURES / ANDROID).open("rb") as f:
            android = org._tiff_from_jpeg(f)
        with (FIXTURES / SAMSUNG).open("rb") as f:
            samsung = org._tiff_from_jpeg(f)
        for name, tiff in ((IPHONE, iphone), (ANDROID, android), (SAMSUNG, samsung)):
            ifd0, sub = self.ifd_tags(tiff)
            with self.subTest(name):
                self.assertLessEqual(ifd0, IFD0_ALLOWED)
                self.assertLessEqual(sub, EXIF_ALLOWED)

    def test_no_location_make_model_or_software_strings(self):
        for name in (IPHONE, ANDROID, REENCODED, SAMSUNG):
            data = self.raw(name)
            # includes the strings Samsung writes into its trailer: network country code, UTC time, scene info
            for needle in (b"GPS", b"Samsung", b"SAMSUNG", b"Xiaomi", b"Qualcomm", b"iPhone", b"Software", b"MakerNote",
                           b"MCC_", b"Image_UTC", b"Camera_", b"Galaxy", b"SM-A"):
                with self.subTest(name=name, needle=needle):
                    self.assertNotIn(needle, data)

    def test_no_image_data_is_left(self):
        for name in (ANDROID, REENCODED):
            data = self.raw(name)
            tail = data[-40:]
            self.assertTrue(data.endswith(b"\xff\xd9"), name)
            self.assertIn(b"\xff\xda", tail, name)  # the scan header is the last thing before the end marker
            self.assertLess(len(tail) - tail.index(b"\xff\xda"), 20, name)  # no entropy-coded data after it
        self.assertEqual(len(self.raw(IPHONE)), 13880 + 2266)
        samsung = self.raw(SAMSUNG)  # image data would sit between the scan header and the end marker
        scan_header = samsung.rindex(b"\xff\xda")
        self.assertEqual(samsung[scan_header + 2 + struct.unpack_from(">H", samsung, scan_header + 2)[0]:][:2], b"\xff\xd9")

    def test_fixtures_are_small(self):
        for path in FIXTURES.iterdir():
            if path.is_file() and path.suffix.lower() in {".heic", ".jpg"}:
                with self.subTest(path.name):
                    self.assertLess(path.stat().st_size, 100 * 1024)

    def test_fixtures_are_documented(self):
        readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
        for name in (IPHONE, ANDROID, REENCODED, SAMSUNG):
            with self.subTest(name):
                self.assertIn(name, readme)


if __name__ == "__main__":
    unittest.main()
